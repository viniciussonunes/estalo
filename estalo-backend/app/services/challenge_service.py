"""
Geração de Challenge por IA a partir de texto bruto (raw_content) --
POST /challenges/generate (app/routers/challenges.py).

Hospeda dois usos do mesmo motor:

1. Mentor de Inglês Ativo (type="ENGLISH_TUTOR", o default -- ver
   PERSONA_MENTOR_INGLES/_montar_prompt_mentor_ingles): raw_content aqui
   não é "material de estudo pra extrair fatos", é a TENTATIVA do aluno
   em inglês -- o motor corrige. A resposta sai no MESMO formato
   content/explanation/tutor_explanation dos outros tipos, então nenhuma
   peça de infra (validação de schema, retry de JSON, cota, persistência)
   precisa saber a diferença.

2. Genérico (type=FILL_THE_GAP/MULTIPLE_CHOICE/TRUE_FALSE/...): extrai
   conteúdo de um texto de estudo e monta um desafio no formato pedido
   (comportamento original deste módulo, mantido).

A chamada de IA em si passa por _chamar_ia (app/services/ai.py), o mesmo
Adaptador de provedor (Gemini/OpenAI) usado por todo o resto da
plataforma -- respeita a cota diária de tokens por usuário (Quota
Manager) e a troca global de provedor via IA_PROVIDER, sem nenhum código
próprio de chamada HTTP/SDK aqui. Reaproveita _limpar_json (mesmo
utilitário usado por gerar_quiz/gerar_cards_completos) pra tirar a casca
de ```json que a IA às vezes embrulha em volta da resposta.

Isolado de cards.py/tutor_service.py/error_explanation_service.py/
study.py de propósito -- as regras de negócio de inglês (ou de qualquer
tipo de challenge) nunca contaminam o motor de estudos de TI do resto do
app, e vice-versa.
"""
import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import Challenge
from app.schemas.challenge import ChallengeAIPayload
from app.services.ai import IAError, _chamar_ia, _limpar_json

# Um exemplo de `content` por tipo conhecido, só pra guiar o formato --
# não é uma lista fechada: um `type` fora daqui ainda funciona, a IA só
# fica sem exemplo e desenha o formato sozinha (ver _montar_system_prompt).
# ENGLISH_TUTOR não entra aqui -- tem prompt dedicado (_montar_prompt_
# mentor_ingles), não o genérico "gerador de material de estudo" abaixo.
_EXEMPLOS_POR_TIPO = {
    "FILL_THE_GAP": (
        '{"text_with_gap": "A capital da França é ___.", '
        '"correct_answer": "Paris", "distractors": ["Londres", "Roma", "Madri"]}'
    ),
    "MULTIPLE_CHOICE": (
        '{"question": "Qual é a capital da França?", "correct_answer": "Paris", '
        '"distractors": ["Londres", "Roma", "Madri"]}'
    ),
    "TRUE_FALSE": '{"statement": "Paris é a capital da França.", "answer": true}',
}

# Profundidade pedagógica do desafio -- ver ChallengeGenerateRequest.depth
# (schemas/challenge.py). "medium" é o default lá.
_INSTRUCOES_POR_DEPTH = {
    "summary": (
        "Nível de profundidade: RESUMO. Gere uma correção RÁPIDA e direta, focada "
        "só no ponto mais essencial -- sem se aprofundar em detalhes secundários."
    ),
    "medium": (
        "Nível de profundidade: INTERMEDIÁRIO. Gere uma correção de dificuldade "
        "média, com foco em RETENÇÃO -- explicação clara o bastante pra fixar, "
        "sem virar uma aula de gramática inteira."
    ),
    "deep": (
        "Nível de profundidade: PROFUNDO. Gere uma correção COMPLETA, que explore "
        "nuance, alternativas de fraseado e o raciocínio gramatical por trás com "
        "profundidade -- não basta a correção, explique o padrão geral por trás dela."
    ),
}

# --- Mentor de Inglês Ativo (type="ENGLISH_TUTOR") ------------------------

PERSONA_MENTOR_INGLES = """\
Você é um mentor de inglês encorajador e experiente, focado em levar o aluno \
à fluência real -- não em tradução mecânica.

Foco pedagógico: collocations (combinações naturais de palavras que um \
nativo usaria) e gramática CONTEXTUALIZADA -- nunca uma regra solta, sempre \
presa a um exemplo real do que o aluno escreveu.

Estruture toda correção em três partes, sempre:
1. O que o aluno tentou dizer -- reproduza a tentativa dele, sem julgar.
2. Como um nativo diria -- a versão natural e fluente, no registro certo.
3. Por quê -- a lógica da correção (collocation, tempo verbal, preposição, \
ordem das palavras, etc.). Nunca "está errado porque sim".

Tom: encorajador, nunca condescendente -- celebre a tentativa antes de \
corrigir."""

_NIVEIS_CEFR = {
    "A1": "iniciante absoluto -- vocabulário básico, frases muito curtas, sem jargão gramatical",
    "A2": "básico -- vocabulário do dia a dia, frases simples, sem jargão gramatical",
    "B1": "intermediário -- pode usar termos gramaticais simples (ex: \"past simple\"), explicações um pouco mais ricas",
    "B2": "intermediário avançado -- pode discutir nuance básica de registro e escolha de palavras",
    "C1": "avançado -- pode discutir nuance, registro e idiomatismos com profundidade",
    "C2": "proficiente -- feedback no nível de um editor nativo, incluindo estilo e naturalidade",
}


def _montar_prompt_mentor_ingles(depth: str, language_level: str) -> str:
    instrucao_depth = _INSTRUCOES_POR_DEPTH.get(depth, _INSTRUCOES_POR_DEPTH["medium"])
    descricao_nivel = _NIVEIS_CEFR.get(language_level, _NIVEIS_CEFR["B1"])
    return (
        PERSONA_MENTOR_INGLES + "\n\n"
        f'Nível do aluno (CEFR {language_level}): {descricao_nivel}. Calibre '
        "vocabulário e complexidade da explicação pra esse nível.\n\n"
        + instrucao_depth + "\n\n" +
        "Você vai receber uma tentativa do aluno em inglês (uma frase, um "
        "parágrafo, ou uma pergunta sobre como dizer algo). Responda APENAS "
        "com um objeto JSON válido, sem texto antes ou depois, sem markdown, "
        "com EXATAMENTE estas três chaves:\n"
        '- "content": objeto JSON com {"student_attempt": "...", '
        '"native_correction": "...", "why": "...", "collocations": ["...", "..."]}'
        ' -- "collocations" é uma lista curta (0 a 3) de combinações naturais '
        "relevantes destacadas na correção; pode vir vazia se não houver "
        "nenhuma central pra esse caso.\n"
        '- "explanation": string (2-3 frases) resumindo a correção principal '
        "de forma direta.\n"
        '- "tutor_explanation": string, a explicação completa e encorajadora '
        '(o "por quê" desenvolvido, no espírito de mentor, não só uma regra '
        "seca).\n\n"
        "Responda em português em explanation/tutor_explanation/why (o aluno "
        "é brasileiro aprendendo inglês) -- mas mantenha student_attempt/"
        "native_correction em inglês, é o texto sendo corrigido."
    )


def _montar_system_prompt(tipo: str, depth: str, language_level: str) -> str:
    if tipo.upper() == "ENGLISH_TUTOR":
        return _montar_prompt_mentor_ingles(depth, language_level)

    exemplo = _EXEMPLOS_POR_TIPO.get(tipo.upper())
    orientacao = (
        f'Para o tipo "{tipo}", um exemplo de "content" válido é: {exemplo}\n\n'
        if exemplo else
        f'O tipo "{tipo}" não tem um exemplo pré-definido -- desenhe um objeto '
        f'JSON razoável e auto-descritivo pro campo "content" que represente '
        f'esse tipo de desafio de estudo.\n\n'
    )
    instrucao_depth = _INSTRUCOES_POR_DEPTH.get(depth, _INSTRUCOES_POR_DEPTH["medium"])
    return (
        "Você é um gerador de material de estudo. Vai receber um texto bruto "
        "e deve analisá-lo, extrair o conteúdo essencial, e transformar isso "
        f'num desafio de estudo do tipo "{tipo}".\n\n'
        + orientacao +
        instrucao_depth + "\n\n" +
        "Responda APENAS com um objeto JSON válido, sem texto antes ou depois, "
        "sem markdown, com EXATAMENTE estas três chaves:\n"
        '- "content": objeto JSON com o desafio em si, no formato do tipo pedido.\n'
        '- "explanation": string (2-3 frases) explicando por que a resposta '
        "correta está certa.\n"
        '- "tutor_explanation": string, explicação mais longa e didática do '
        "conceito por trás do desafio -- não entregue só a resposta, ensine o "
        "porquê (mesmo espírito do Tutor Inteligente já usado no resto do "
        "Estalo).\n\n"
        "Use o idioma do texto original. Não inclua deck_id nem type no JSON -- "
        "esses campos já são conhecidos por fora e não vêm da sua resposta."
    )


def _parsear_e_validar(bruto: str) -> ChallengeAIPayload:
    """json.JSONDecodeError (não é JSON) ou pydantic.ValidationError (é
    JSON, mas não tem o formato certo) -- as duas são "a IA não obedeceu
    o schema", tratadas do mesmo jeito por quem chama (gerar_challenge)."""
    dados = json.loads(_limpar_json(bruto))
    return ChallengeAIPayload(**dados)


def gerar_challenge(
    deck_id: int,
    raw_content: str,
    tipo: str,
    user_id: int,
    db: Session,
    depth: str = "medium",
    language_level: str = "B1",
    preview_only: bool = False,
) -> Challenge:
    """Gera (via IA) um Challenge a partir de texto bruto -- PERSISTE por
    padrão; se `preview_only=True`, devolve o objeto gerado sem chamar
    db.add()/db.commit() (id/created_at ficam None, ver ChallengeResponse).

    `depth` ("summary" | "medium" | "deep") e `language_level` (CEFR
    A1-C2, só efetivamente usado quando tipo="ENGLISH_TUTOR") entram no
    system prompt como instruções -- não mudam nada da validação/
    persistência abaixo, só o que é pedido à IA.

    Validação de segurança: se a primeira resposta da IA não for um JSON
    válido no formato de ChallengeAIPayload, faz UMA tentativa de correção
    (manda de volta o que ela respondeu + o erro de validação, pede pra
    corrigir). Cada tentativa é uma chamada de IA de verdade -- passa pelo
    quota-check do adaptador como qualquer outra (2 chamadas malsucedidas
    custam 2x da cota; isso vale igual pra preview_only=True -- gerar um
    preview ainda é uma chamada de IA real, não é grátis). Se ainda assim
    falhar, levanta IAError com uma mensagem clara -- nunca deixa um
    JSONDecodeError/ValidationError cru escapar pro router.
    """
    system_prompt = _montar_system_prompt(tipo, depth, language_level)
    bruto = _chamar_ia(raw_content, user_id, db, instrucao_sistema=system_prompt)

    try:
        payload = _parsear_e_validar(bruto)
    except (json.JSONDecodeError, ValidationError) as erro_original:
        prompt_correcao = (
            "A resposta anterior não é um JSON válido no formato pedido.\n\n"
            f"Resposta recebida:\n{bruto}\n\n"
            f"Erro de validação: {erro_original}\n\n"
            "Corrija e responda APENAS com o JSON válido, no mesmo formato "
            "pedido antes (chaves content/explanation/tutor_explanation), "
            "sem texto extra nem markdown."
        )
        bruto_corrigido = _chamar_ia(
            prompt_correcao, user_id, db, instrucao_sistema=system_prompt,
        )
        try:
            payload = _parsear_e_validar(bruto_corrigido)
        except (json.JSONDecodeError, ValidationError) as erro_final:
            raise IAError(
                "A IA não conseguiu gerar um challenge em formato válido, "
                f"mesmo após uma tentativa de correção ({erro_final})."
            ) from erro_final

    # Telemetria leve: só type + language_level, pra dar visibilidade de
    # uso (ex: "quantos ENGLISH_TUTOR em C1 essa semana") via logs da
    # Vercel, sem guardar nada sensível -- nunca raw_content/content
    # gerado, nunca user_id/deck_id. print() (não logging) de propósito:
    # não há handler de logging configurado neste projeto (nível padrão
    # do root logger é WARNING, um logger.info() aqui simplesmente não
    # apareceria em lugar nenhum sem configurar isso à parte) -- stdout é
    # sempre capturado pela Vercel, então isto funciona sem depender de
    # nenhuma configuração adicional. Roda só depois do payload validado
    # com sucesso (1ª tentativa ou após correção) -- nunca em falha.
    print(f"[challenge_generated] type={tipo} language_level={language_level or 'n/a'}")

    challenge = Challenge(
        deck_id=deck_id,
        type=tipo,
        content=payload.content,
        explanation=payload.explanation,
        tutor_explanation=payload.tutor_explanation,
        # language_level só faz sentido guardado pra tipos de idioma --
        # nos demais tipos fica None (a coluna existe, mas não se aplica).
        language_level=language_level if tipo.upper() == "ENGLISH_TUTOR" else None,
    )

    if preview_only:
        # Nunca passa por add()/commit() -- id/created_at continuam None
        # no objeto Python (created_at usa default=func.now(), que só é
        # aplicado pelo SQLAlchemy no INSERT). ChallengeResponse já aceita
        # os dois como opcionais exatamente pra este caso.
        return challenge

    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge
