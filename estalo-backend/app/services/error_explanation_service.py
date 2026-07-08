"""
Tutor Inteligente Evolutivo — explica por que UMA alternativa específica
está errada (não o card em geral, isso é o tutor_service.py), com cache
versionado que evolui via feedback do usuário (👍/👎).

Arquitetura espelha Review/ReviewHistory: ExplanationCache é o estado
atual mutável (uma linha por par card+alternativa), ExplanationLog é o
log imutável de cada transição (só auditoria/debug). As duas escritas
sempre acontecem juntas, no mesmo commit -- nunca uma sem a outra.

Reaproveita a persona do Tutor (tutor_service.py) por consistência de
tom -- não faz sentido o usuário ouvir "vozes" diferentes dependendo de
qual botão de ajuda ele clicou.

--- Padrão Adaptador (provedor de IA) ---
_chamar_ia() é o adaptador: todo o resto deste arquivo (explicar_erro,
refinar_explicacao, os montadores de prompt) fala só com ela, nunca
direto com Gemini ou OpenAI. Ela decide, com base em settings.IA_PROVIDER
("gemini" ou "openai"), pra qual _chamar_<provedor>_raw() despachar --
mas sempre recebe um prompt (+ instrucao_sistema opcional) e devolve
texto puro, não importa o provedor por trás. Trocar de IA é mudar
IA_PROVIDER (env var) e reiniciar; nenhuma linha de explicar_erro/
refinar_explicacao muda.

O quota-check (Quota Manager, ver quota_service.py) acontece DENTRO do
adaptador, uma única vez, ANTES de escolher o provedor -- não dentro de
cada _chamar_<provedor>_raw(), pra não arriscar debitar a cota duas vezes
(ou nenhuma) dependendo de qual branch fosse seguida.
"""
import os
import time

import sentry_sdk
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.explanation_cache import ExplanationCache
from app.models.explanation_log import ExplanationLog
from app.schemas.error_explanation import ExplanationOut
from app.services.ai import IAError, QuotaExceededError, _chamar_gemini_raw, _estimar_tokens
from app.services.quota_service import check_and_consume_tokens
from app.services.tutor_service import PERSONA_TUTOR, TUTOR_MODEL

# Teto de refinamentos por par (card, alternativa) -- sem isso, um usuário
# insatisfeito poderia dar 👎 indefinidamente, cada um gastando uma chamada
# de IA (e cota, ver quota_service). 5 tentativas de refinar uma explicação
# didática é uma folga generosa; depois disso, paramos de chamar a IA pra
# esse par especificamente (outros pares continuam livres).
MAX_VERSAO = 5

# gpt-4o-mini: equivalente de custo/latência ao gemini-2.5-flash-lite já
# usado no Gemini -- resposta sob demanda durante o estudo é sensível a
# latência, não é geração em lote.
OPENAI_MODEL = "gpt-4o-mini"

# Erros transitórios (rate limit, timeout, falha de conexão, 5xx do lado
# da OpenAI) valem uma 2ª tentativa -- mesmo espírito do _RETRY_STATUS
# usado pro Gemini (app/services/ai.py). Qualquer outro OpenAIError
# (chave inválida, saldo zerado, prompt rejeitado etc.) tentar de novo
# não muda o resultado, então é levantado na hora.
_OPENAI_RETRYAVEL = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)


def _chamar_openai_raw(
    prompt: str,
    timeout: int = 25,
    instrucao_sistema: str | None = None,
    model: str = OPENAI_MODEL,
) -> str:
    """Equivalente a _chamar_gemini_raw (app/services/ai.py), mas pra
    OpenAI via biblioteca oficial `openai` -- MESMA entrada
    (prompt/instrucao_sistema) e saída (texto puro) que o adaptador
    espera, só a implementação por trás muda.

    A chave é lida do ambiente com os.getenv primeiro -- em produção
    (Vercel) OPENAI_API_KEY já é uma env var de verdade, então resolve
    direto; localmente, quando só existe no .env (pydantic-settings não
    exporta pro processo), cai no fallback settings.OPENAI_API_KEY. Só é
    validada/lida AQUI, no momento em que o provedor "openai" é de fato
    escolhido -- rodar com IA_PROVIDER=gemini (padrão) nunca exige
    OPENAI_API_KEY configurada.
    """
    api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
    if not api_key:
        raise IAError("Chave da OpenAI não configurada. Preencha OPENAI_API_KEY no arquivo .env")

    # instrucao_sistema vira a mensagem "system" -- equivalente ao
    # systemInstruction separado do Gemini, mesma separação persona/
    # conteúdo, só que no formato de mensagens da OpenAI.
    messages = []
    if instrucao_sistema:
        messages.append({"role": "system", "content": instrucao_sistema})
    messages.append({"role": "user", "content": prompt})

    cliente = OpenAI(api_key=api_key, timeout=timeout)

    ultimo_erro: Exception | None = None
    for tentativa in range(2):
        if tentativa > 0:
            time.sleep(2)
        try:
            resposta = cliente.chat.completions.create(model=model, messages=messages)
        except _OPENAI_RETRYAVEL as e:
            # Captura explícita no Sentry ANTES de virar IAError: o
            # router (study.py) sempre pega IAError e devolve um
            # 503/429 genérico ao usuário -- sem esse capture aqui, o
            # Sentry nunca veria o erro real da OpenAI (rate limit,
            # timeout, 5xx), porque a exceção nunca escapa não-tratada.
            sentry_sdk.capture_exception(e)
            ultimo_erro = e
            if tentativa < 1:
                continue
            break
        except OpenAIError as e:
            # Não-retryable: chave inválida, saldo/cota esgotados,
            # prompt rejeitado etc. -- tentar de novo não resolve.
            sentry_sdk.capture_exception(e)
            raise IAError(f"OpenAI respondeu com erro: {e}") from e

        try:
            return resposta.choices[0].message.content
        except (IndexError, AttributeError) as e:
            raise IAError("Resposta da OpenAI veio em formato inesperado") from e

    raise IAError(f"OpenAI indisponível após 2 tentativas ({ultimo_erro})")


def _chamar_ia(
    prompt: str,
    user_id: int,
    db: Session,
    instrucao_sistema: str | None = None,
    timeout: int = 25,
) -> str:
    """O Adaptador. Único ponto deste arquivo que sabe que existe mais de
    um provedor de IA -- explicar_erro/refinar_explicacao só chamam isto,
    nunca _chamar_gemini_raw/_chamar_openai_raw diretamente.
    """
    estimativa = _estimar_tokens(prompt, instrucao_sistema)
    if not check_and_consume_tokens(user_id, estimativa, db):
        raise QuotaExceededError(
            "Limite diário de uso do Tutor/IA atingido. Tente novamente amanhã."
        )

    provider = settings.IA_PROVIDER.strip().lower()
    if provider == "openai":
        return _chamar_openai_raw(prompt, timeout=timeout, instrucao_sistema=instrucao_sistema)
    if provider == "gemini":
        return _chamar_gemini_raw(prompt, timeout=timeout, instrucao_sistema=instrucao_sistema, model=TUTOR_MODEL)
    raise IAError(f"IA_PROVIDER '{provider}' desconhecido -- use 'gemini' ou 'openai'.")


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
    texto = _chamar_ia(prompt, user_id, db, instrucao_sistema=PERSONA_TUTOR)

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
    texto_novo = _chamar_ia(prompt, user_id, db, instrucao_sistema=PERSONA_TUTOR)

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
