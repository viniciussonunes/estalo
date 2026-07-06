"""
Tutor Inteligente Evolutivo — explica por que UMA alternativa específica
está errada (não o card em geral, isso é o tutor_service.py), com cache
versionado que evolui via feedback do usuário (👍/👎).

Arquitetura espelha Review/ReviewHistory: ExplanationCache é o estado
atual mutável (uma linha por par card+alternativa), ExplanationLog é o
log imutável de cada transição (só auditoria/debug). As duas escritas
sempre acontecem juntas, no mesmo commit -- nunca uma sem a outra.

Reaproveita a persona e o modelo do Tutor (tutor_service.py) por
consistência de tom/custo -- não faz sentido o usuário ouvir "vozes"
diferentes dependendo de qual botão de ajuda ele clicou.
"""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.explanation_cache import ExplanationCache
from app.models.explanation_log import ExplanationLog
from app.schemas.error_explanation import ExplanationOut
from app.services.ai import _chamar_gemini
from app.services.tutor_service import PERSONA_TUTOR, TUTOR_MODEL

# Teto de refinamentos por par (card, alternativa) -- sem isso, um usuário
# insatisfeito poderia dar 👎 indefinidamente, cada um gastando uma chamada
# de IA (e cota, ver quota_service). 5 tentativas de refinar uma explicação
# didática é uma folga generosa; depois disso, paramos de chamar o Gemini
# pra esse par especificamente (outros pares continuam livres).
MAX_VERSAO = 5


def _montar_prompt_nova_explicacao(card_front: str, card_back: str, alternativa_escolhida: str) -> str:
    return (
        "O aluno respondeu esta pergunta de múltipla escolha errado.\n"
        "---\n"
        f"[Pergunta]: {card_front}\n"
        f"[Resposta correta]: {card_back}\n"
        f"[Alternativa que o aluno escolheu, incorreta]: {alternativa_escolhida}\n"
        "---\n"
        "Explique por que a alternativa escolhida está incorreta e reforce, "
        "de forma didática, por que a resposta correta é a certa. Siga as "
        "diretrizes de tutor acima."
    )


def _montar_prompt_refinamento(
    card_front: str,
    card_back: str,
    alternativa_escolhida: str,
    explicacao_atual: str,
    motivo: str,
) -> str:
    # Contexto "Markov" de propósito (decisão tomada com o usuário): só a
    # ÚLTIMA explicação + o motivo mais recente, nunca o histórico
    # acumulado de tentativas anteriores -- prompt de tamanho constante a
    # cada refinamento, em vez de crescer a cada 👎 (ver ExplanationLog
    # pra quem quiser o histórico completo, isso não vai pro prompt).
    return (
        "Você já explicou por que uma alternativa estava incorreta, mas o "
        "aluno achou a explicação insatisfatória e pediu uma melhor.\n"
        "---\n"
        f"[Pergunta]: {card_front}\n"
        f"[Resposta correta]: {card_back}\n"
        f"[Alternativa incorreta escolhida]: {alternativa_escolhida}\n"
        f"[Sua explicação anterior]: {explicacao_atual}\n"
        f"[Por que o aluno não gostou dela]: {motivo}\n"
        "---\n"
        "Gere uma NOVA explicação, melhor, que resolva o problema apontado "
        "pelo aluno. Não repita a explicação anterior -- refine de verdade. "
        "Siga as diretrizes de tutor acima."
    )


def _buscar_cache(card_id: int, alternativa_escolhida: str, db: Session) -> ExplanationCache | None:
    return (
        db.query(ExplanationCache)
        .filter(
            ExplanationCache.card_id == card_id,
            ExplanationCache.alternativa_escolhida == alternativa_escolhida,
        )
        .first()
    )


def explicar_erro(
    card_id: int,
    card_front: str,
    card_back: str,
    alternativa_escolhida: str,
    user_id: int,
    db: Session,
) -> ExplanationOut:
    """Hit: devolve o que já está em cache, sem gastar IA de novo.
    Miss: gera a v1 via Gemini e grava cache + log atomicamente."""
    cache = _buscar_cache(card_id, alternativa_escolhida, db)
    if cache is not None:
        return ExplanationOut(explanation=cache.texto_explicacao_atual, versao=cache.versao)

    prompt = _montar_prompt_nova_explicacao(card_front, card_back, alternativa_escolhida)
    texto = _chamar_gemini(prompt, user_id, db, instrucao_sistema=PERSONA_TUTOR, model=TUTOR_MODEL)

    novo = ExplanationCache(
        card_id=card_id,
        alternativa_escolhida=alternativa_escolhida,
        texto_explicacao_atual=texto,
        motivo_rejeicao_mais_recente=None,
        versao=1,
    )
    db.add(novo)
    try:
        db.flush()  # precisa do id gerado antes de criar o log
    except IntegrityError:
        # Corrida rara: duas requests concorrentes criando a v1 pro MESMO
        # par card+alternativa ao mesmo tempo (ex: duplo-clique). O índice
        # único (ix_explanation_cache_card_alt) barra a segunda -- em vez
        # de estourar 500, devolve o que a primeira já criou.
        db.rollback()
        cache = _buscar_cache(card_id, alternativa_escolhida, db)
        return ExplanationOut(explanation=cache.texto_explicacao_atual, versao=cache.versao)

    db.add(ExplanationLog(
        explanation_cache_id=novo.id, versao=1, texto_explicacao=texto, motivo_rejeicao=None,
    ))
    db.commit()

    return ExplanationOut(explanation=novo.texto_explicacao_atual, versao=novo.versao)


def refinar_explicacao(
    cache: ExplanationCache,
    card_front: str,
    card_back: str,
    motivo: str,
    user_id: int,
    db: Session,
) -> ExplanationOut:
    """Aplica feedback negativo: gera uma versão refinada via Gemini,
    salvando cache + log atomicamente. Idempotente por conteúdo (retry com
    o MESMO motivo não gasta IA nem incrementa versão de novo) e limitado
    por MAX_VERSAO (depois disso, para de tentar refinar esse par)."""
    if motivo == cache.motivo_rejeicao_mais_recente:
        return ExplanationOut(explanation=cache.texto_explicacao_atual, versao=cache.versao)

    if cache.versao >= MAX_VERSAO:
        return ExplanationOut(
            explanation=cache.texto_explicacao_atual, versao=cache.versao, limite_atingido=True,
        )

    prompt = _montar_prompt_refinamento(
        card_front, card_back, cache.alternativa_escolhida, cache.texto_explicacao_atual, motivo,
    )
    texto_novo = _chamar_gemini(prompt, user_id, db, instrucao_sistema=PERSONA_TUTOR, model=TUTOR_MODEL)

    cache.texto_explicacao_atual = texto_novo
    cache.motivo_rejeicao_mais_recente = motivo
    cache.versao += 1
    db.add(ExplanationLog(
        explanation_cache_id=cache.id,
        versao=cache.versao,
        texto_explicacao=texto_novo,
        motivo_rejeicao=motivo,
    ))
    db.commit()

    return ExplanationOut(explanation=cache.texto_explicacao_atual, versao=cache.versao)
