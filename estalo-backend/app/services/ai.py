"""
Serviço de IA — gera cards a partir de um texto, e concentra o Adaptador de
provedor de IA (Gemini/OpenAI) usado por toda a plataforma.

A ideia (sua dor #1): você entrega um texto de estudo e a IA devolve pares
pergunta/resposta prontos. O "monitor" lê suas anotações e cria as perguntas
de revisão.

Decisão importante: pedimos a resposta em JSON ESTRUTURADO, não texto solto.
Assim o código lê com segurança, sem adivinhar onde acaba a pergunta e começa
a resposta. É a diferença entre receber um formulário preenchido e um bilhete
escrito à mão.

--- Padrão Adaptador (provedor de IA) ---
_chamar_ia() é o único ponto de todo o backend que sabe que existe mais de um
provedor de IA -- gerar_quiz/gerar_explicacoes/gerar_cards_completos/
gerar_cards (abaixo), tutor_service.explicar_card e
error_explanation_service.explicar_erro/refinar_explicacao chamam só ela,
nunca _chamar_gemini_raw/_chamar_openai_raw diretamente. Ela decide, com base
em settings.IA_PROVIDER ("gemini" ou "openai"), pra qual _chamar_<provedor>_raw()
despachar -- mas sempre recebe um prompt (+ instrucao_sistema opcional) e
devolve texto puro, não importa o provedor por trás. Trocar de IA pra toda a
plataforma de uma vez é mudar IA_PROVIDER (env var) e reiniciar; nenhuma
linha de código de negócio muda.

O quota-check (Quota Manager, ver quota_service.py) acontece DENTRO do
adaptador, uma única vez, ANTES de escolher o provedor -- não dentro de cada
_chamar_<provedor>_raw(), pra não arriscar debitar a cota duas vezes (ou
nenhuma) dependendo de qual branch fosse seguida.
"""
import json
import math
import os
import time

import httpx
import sentry_sdk
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.quota_service import check_and_consume_tokens

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

# gpt-4o-mini: equivalente de custo/latência ao gemini-2.5-flash-lite já
# usado nos serviços sensíveis a latência (tutor_service, error_explanation_
# service) -- resposta sob demanda durante o estudo não pode ser lenta.
OPENAI_MODEL = "gpt-4o-mini"


class IAError(Exception):
    """Erro ao falar com a IA (chave faltando, API fora do ar, resposta estranha)."""


class QuotaExceededError(IAError):
    """Usuário estourou o limite diário de tokens de IA (Quota Manager).

    Subclassa IAError (não Exception pura) de propósito: todo router que
    já trata `except IAError` (cards.py, study.py) passa a tratar isso
    também, de graça -- sem precisar de um `except QuotaExceededError`
    novo em cada endpoint que chama IA.
    """


_RETRY_STATUS = {429, 500, 502, 503, 504}


def _estimar_tokens(prompt: str, instrucao_sistema: str | None = None) -> int:
    """Estimativa grosseira de propósito: ~4 caracteres por token (regra de
    bolso comum, não a contagem exata do tokenizer do Gemini). O objetivo
    aqui não é precisão -- é ter um teto que barre ANTES de gastar cota
    numa chamada, mesmo com folga de margem de erro na estimativa.
    """
    total_chars = len(prompt) + len(instrucao_sistema or "")
    return math.ceil(total_chars / 4)


def _chamar_gemini_raw(
    prompt: str,
    timeout: int = 25,
    instrucao_sistema: str | None = None,
    model: str | None = None,
    desabilitar_thinking: bool = False,
) -> str:
    """Só a chamada HTTP ao Gemini, SEM quota-check -- usada por _chamar_ia()
    (abaixo), o Adaptador de provedor de IA, que faz o quota-check UMA
    única vez antes de escolher pra qual provedor despachar. Se essa
    função fizesse o quota-check internamente, trocar de provedor no
    adaptador arriscaria debitar a cota duas vezes (uma no adaptador,
    outra aqui).

    Tenta até 2 vezes em erros transitórios. Orçamento de tempo pensado
    pra caber numa função serverless: 2 tentativas de até `timeout`s
    cada, com 2s de espera entre elas — pior caso ~2*timeout + 2s.

    `instrucao_sistema`, quando informado, vai no campo `systemInstruction`
    da própria API — separado de `contents` de propósito. É o que faz a
    persona (tom, regras, formatação) ficar estável entre chamadas, sem
    competir com o conteúdo específico de cada prompt.

    `model`, quando informado, sobrepõe settings.GEMINI_MODEL só nesta
    chamada — permite um serviço (ex: tutor_service) usar um modelo mais
    rápido/barato sem mudar o modelo padrão usado por gerar_cards/gerar_quiz.

    `desabilitar_thinking`, quando True, zera o thinkingBudget do Gemini
    2.5 -- usado por gerar_cards/gerar_quiz, onde a tarefa é só formatar
    JSON estruturado seguindo regras explícitas (nada que precise de
    raciocínio profundo). Medido empiricamente: pra um lote de 10 cards,
    o "pensamento" consumia ~5x mais tokens que a resposta em si e
    quase dobrava o tempo (32s -> 13s sem), arriscando estourar o timeout
    do endpoint e até truncar o JSON no meio (finishReason MAX_TOKENS).
    """
    if not settings.GEMINI_API_KEY:
        raise IAError("Chave do Gemini não configurada. Preencha GEMINI_API_KEY no arquivo .env")

    url = GEMINI_URL.format(model=model or settings.GEMINI_MODEL)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    if desabilitar_thinking:
        payload["generationConfig"] = {"thinkingConfig": {"thinkingBudget": 0}}
    if instrucao_sistema:
        payload["systemInstruction"] = {"parts": [{"text": instrucao_sistema}]}
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": settings.GEMINI_API_KEY,
    }

    ultimo_erro: Exception | None = None
    for tentativa in range(2):
        if tentativa > 0:
            time.sleep(2)
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.RequestError as e:
            raise IAError(f"Falha ao conectar no Gemini: {e}") from e

        if resp.status_code in _RETRY_STATUS:
            ultimo_erro = Exception(f"status {resp.status_code}")
            if tentativa < 1:
                continue
            break  # também falhou na última tentativa -> cai no raise genérico abaixo

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise IAError(f"Gemini respondeu com erro {e.response.status_code}") from e

        try:
            dados = resp.json()
            return dados["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise IAError("Resposta do Gemini veio em formato inesperado") from e

    raise IAError(f"Gemini indisponível após 2 tentativas ({ultimo_erro})")


# Erros transitórios (rate limit, timeout, falha de conexão, 5xx do lado da
# OpenAI) valem uma 2ª tentativa -- mesmo espírito do _RETRY_STATUS usado pro
# Gemini acima. Qualquer outro OpenAIError (chave inválida, saldo zerado,
# prompt rejeitado etc.) tentar de novo não muda o resultado, então é
# levantado na hora.
_OPENAI_RETRYAVEL = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)


def _chamar_openai_raw(
    prompt: str,
    timeout: int = 25,
    instrucao_sistema: str | None = None,
    model: str = OPENAI_MODEL,
) -> str:
    """Equivalente a _chamar_gemini_raw acima, mas pra OpenAI via
    biblioteca oficial `openai` -- MESMA entrada (prompt/instrucao_sistema)
    e saída (texto puro) que o adaptador espera, só a implementação por
    trás muda.

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
            # Captura explícita no Sentry ANTES de virar IAError: os
            # routers sempre pegam IAError e devolvem um 503/429 genérico
            # ao usuário -- sem esse capture aqui, o Sentry nunca veria o
            # erro real da OpenAI (rate limit, timeout, 5xx), porque a
            # exceção nunca escapa não-tratada.
            sentry_sdk.capture_exception(e)
            ultimo_erro = e
            if tentativa < 1:
                continue
            break
        except OpenAIError as e:
            # Não-retryable: chave inválida, saldo/cota esgotados, prompt
            # rejeitado etc. -- tentar de novo não resolve.
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
    timeout: int = 25,
    instrucao_sistema: str | None = None,
    model: str | None = None,
    desabilitar_thinking: bool = False,
) -> str:
    """O Adaptador. Único ponto que decide pra qual provedor despachar --
    todo o resto do backend chama isto, nunca _chamar_gemini_raw/
    _chamar_openai_raw diretamente.

    `user_id`/`db` alimentam o Quota Manager (app/services/quota_service.py):
    a estimativa de tokens é debitada da cota do usuário ANTES da chamada
    à IA -- se ele já estourou o limite diário, nem tentamos falar com o
    provedor (ver QuotaExceededError acima).

    `model`, quando informado, sobrepõe o modelo padrão só pro Gemini (ex:
    tutor_service usa um modelo mais rápido/barato que gerar_cards/
    gerar_quiz) -- a OpenAI usa sempre OPENAI_MODEL, sem variação por
    serviço (não há necessidade disso hoje).

    `desabilitar_thinking` só tem efeito no Gemini (ver _chamar_gemini_raw)
    -- a OpenAI não tem esse conceito, então o parâmetro é ignorado nesse
    branch.
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
        return _chamar_gemini_raw(
            prompt, timeout=timeout, instrucao_sistema=instrucao_sistema, model=model,
            desabilitar_thinking=desabilitar_thinking,
        )
    raise IAError(f"IA_PROVIDER '{provider}' desconhecido -- use 'gemini' ou 'openai'.")


def _montar_prompt(texto: str, quantidade: int) -> str:
    """Prompt legado: gera só front/back (para cards manuais sem quiz)."""
    return (
        f"Você é um gerador de flashcards de estudo. A partir do TEXTO abaixo, "
        f"crie exatamente {quantidade} flashcards no estilo pergunta e resposta.\n"
        f"Regras:\n"
        f"- Cada flashcard tem 'front' (pergunta clara e objetiva) e 'back' (resposta concisa).\n"
        f"- Use o idioma do texto.\n"
        f"- Responda APENAS com um array JSON válido, sem texto antes ou depois, "
        f"sem marcação de código.\n"
        f'- Formato: [{{"front": "...", "back": "..."}}]\n\n'
        f"TEXTO:\n{texto}"
    )


def _montar_prompt_completo(texto: str, quantidade: int) -> str:
    """Gera cards completos: front, back, 3 distratores exclusivos e explicação."""
    return (
        f"Você é um gerador de flashcards educativos completos. A partir do TEXTO abaixo, "
        f"crie exatamente {quantidade} flashcards.\n\n"
        f"Para cada flashcard gere:\n"
        f"1. 'front': Pergunta clara e objetiva baseada no conteúdo.\n"
        f"2. 'back': Resposta correta e concisa.\n"
        f"3. 'distractors': Lista de EXATAMENTE 3 alternativas INCORRETAS. REGRA DE TAMANHO "
        f"OBRIGATÓRIA E MENSURÁVEL: conte o número de caracteres do 'back' -- cada distractor "
        f"tem que ter entre 90% e 110% desse número de caracteres. Um distractor fora dessa "
        f"faixa é uma resposta ERRADA à tarefa, não só uma questão de estilo. Para bater essa "
        f"faixa, adicione detalhes/contexto extra ao distractor até ele ficar do tamanho da "
        f"resposta certa -- nunca deixe um distractor curto e genérico. Além disso, os "
        f"distractors devem ser:\n"
        f"   - Plausíveis e relacionados especificamente a ESTA pergunta\n"
        f"   - Gerados de forma exclusiva para este card (NUNCA copie o 'back' de outros cards)\n"
        f"   - Distintos entre si e da resposta correta\n"
        f"4. 'explanation': Explicação de 2-3 frases explicando POR QUÊ a resposta correta está certa.\n\n"
        f"Regras gerais:\n"
        f"- Use o idioma do texto.\n"
        f"- Responda APENAS com um array JSON válido, sem texto antes ou depois, sem markdown.\n"
        f'- Formato exato: [{{"front":"...","back":"...","distractors":["...","...","..."],"explanation":"..."}}]\n\n'
        f"TEXTO:\n{texto}"
    )


def _distractors_equilibrados(correct: str, distractors: list) -> bool:
    """Rede de segurança contra o prompt ser ignorado: se algum distractor
    ficar visivelmente mais curto que a resposta certa, o tamanho do texto
    vira uma pista visual da resposta (bug real reportado por usuário -- ver
    _montar_prompt_quiz/_montar_prompt_completo, que já pedem 90%-110% do
    tamanho do 'back'). Aqui só rejeitamos o caso degenerado (< 50%), sem
    replicar a faixa inteira do prompt -- variação normal de estilo não deve
    derrubar um card válido.
    """
    limite = len(correct) * 0.5
    return all(len(str(d)) >= limite for d in distractors)


def _limpar_json(bruto: str) -> str:
    """
    Às vezes a IA embrulha o JSON em ```json ... ```. Tira essa casca
    pra sobrar só o array puro.
    """
    bruto = bruto.strip()
    if bruto.startswith("```"):
        # remove a primeira linha (```json) e a última (```)
        linhas = bruto.split("\n")
        linhas = [l for l in linhas if not l.strip().startswith("```")]
        bruto = "\n".join(linhas).strip()
    return bruto


def _montar_prompt_quiz(cards: list[dict]) -> str:
    cards_json = json.dumps(cards, ensure_ascii=False, indent=2)
    return (
        "Você é um gerador de quiz educativo. Para cada flashcard abaixo, crie uma questão de múltipla escolha.\n\n"
        "REGRAS OBRIGATÓRIAS:\n"
        "1. Use a 'front' do card como base para a pergunta.\n"
        "2. Use o 'back' como a única resposta correta ('correct').\n"
        "3. Crie EXATAMENTE 3 alternativas INCORRETAS ('distractors'). REGRA DE TAMANHO "
        "OBRIGATÓRIA E MENSURÁVEL: conte o número de caracteres do 'back' -- cada distractor "
        "tem que ter entre 90% e 110% desse número de caracteres. Um distractor fora dessa "
        "faixa é uma resposta ERRADA à tarefa, não só uma questão de estilo. Para bater essa "
        "faixa, adicione detalhes/contexto extra ao distractor até ele ficar do tamanho da "
        "resposta certa -- nunca deixe um distractor curto e genérico. Além disso, os "
        "distractors devem ser:\n"
        "   - Plausíveis e contextualizados para AQUELA pergunta específica\n"
        "   - Gerados exclusivamente para esse card (NUNCA copie o 'back' de outros cards)\n"
        "   - Distintos entre si e distintos da resposta correta\n"
        "4. Escreva uma 'explanation' curta (1-3 frases) explicando por que a resposta correta é a certa.\n"
        "5. Preserve o 'card_id' exato de cada flashcard na resposta.\n"
        "6. Use o mesmo idioma dos flashcards.\n\n"
        "Responda APENAS com um array JSON válido, sem texto antes ou depois, sem markdown.\n"
        'Formato exato: [{"card_id": N, "question": "...", "correct": "...", '
        '"distractors": ["...", "...", "..."], "explanation": "..."}]\n\n'
        f"FLASHCARDS:\n{cards_json}"
    )


def _montar_prompt_revelar(cards: list[dict]) -> str:
    cards_json = json.dumps(cards, ensure_ascii=False, indent=2)
    return (
        "Você é um assistente de estudo. Para cada flashcard abaixo, escreva uma explicação "
        "que ajude o estudante a entender e memorizar a resposta.\n\n"
        "A explicação deve:\n"
        "- Contextualizar o conceito\n"
        "- Explicar o PORQUÊ da resposta ser correta\n"
        "- Ter entre 2 e 4 frases\n"
        "- Usar o mesmo idioma do flashcard\n"
        "- Preservar o 'card_id' exato de cada flashcard na resposta\n\n"
        "Responda APENAS com um array JSON válido, sem texto antes ou depois, sem markdown.\n"
        'Formato exato: [{"card_id": N, "explanation": "..."}]\n\n'
        f"FLASHCARDS:\n{cards_json}"
    )


def gerar_quiz(cards: list[dict], user_id: int, db: Session) -> list[dict]:
    """
    Recebe lista de {card_id, front, back} e devolve lista de
    {card_id, question, correct, distractors, explanation}.
    Lança IAError (ou QuotaExceededError) se algo der errado.
    """
    bruto = _chamar_ia(_montar_prompt_quiz(cards), user_id, db, desabilitar_thinking=True)

    try:
        resultado = json.loads(_limpar_json(bruto))
    except json.JSONDecodeError as e:
        raise IAError("A IA não devolveu um JSON válido") from e

    validos = []
    for item in resultado:
        if not isinstance(item, dict):
            continue
        if not all(k in item for k in ("card_id", "question", "correct", "distractors", "explanation")):
            continue
        distractors = item["distractors"]
        if not isinstance(distractors, list) or len(distractors) < 3:
            continue
        correct = str(item["correct"])
        distractors = [str(d) for d in distractors[:3]]
        if not _distractors_equilibrados(correct, distractors):
            continue
        validos.append({
            "card_id": int(item["card_id"]),
            "question": str(item["question"]),
            "correct": correct,
            "distractors": distractors,
            "explanation": str(item["explanation"]),
        })

    if not validos:
        raise IAError("A IA não gerou questões válidas")

    return validos


def gerar_explicacoes(cards: list[dict], user_id: int, db: Session) -> list[dict]:
    """
    Recebe lista de {card_id, front, back} e devolve lista de
    {card_id, explanation}.
    Lança IAError (ou QuotaExceededError) se algo der errado.
    """
    bruto = _chamar_ia(_montar_prompt_revelar(cards), user_id, db)

    try:
        resultado = json.loads(_limpar_json(bruto))
    except json.JSONDecodeError as e:
        raise IAError("A IA não devolveu um JSON válido") from e

    validos = []
    for item in resultado:
        if isinstance(item, dict) and "card_id" in item and "explanation" in item:
            validos.append({
                "card_id": int(item["card_id"]),
                "explanation": str(item["explanation"]),
            })

    if not validos:
        raise IAError("A IA não gerou explicações válidas")

    return validos


def gerar_cards_completos(texto: str, quantidade: int, user_id: int, db: Session) -> list[dict]:
    """
    Gera cards com front, back, distractors e explanation em uma única chamada.
    Retorna lista de dicts com todas as chaves preenchidas.
    """
    bruto = _chamar_ia(
        _montar_prompt_completo(texto, quantidade), user_id, db, timeout=30,
        desabilitar_thinking=True,
    )

    try:
        cards = json.loads(_limpar_json(bruto))
    except json.JSONDecodeError as e:
        raise IAError("A IA não devolveu um JSON válido") from e

    validos = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        if not all(k in c for k in ("front", "back", "distractors", "explanation")):
            continue
        distractors = c["distractors"]
        if not isinstance(distractors, list) or len(distractors) < 3:
            continue
        back = str(c["back"])
        distractors = [str(d) for d in distractors[:3]]
        if not _distractors_equilibrados(back, distractors):
            continue
        validos.append({
            "front":        str(c["front"]),
            "back":         back,
            "distractors":  distractors,
            "explanation":  str(c["explanation"]),
        })

    if not validos:
        raise IAError("A IA não gerou cards válidos com a estrutura completa")

    return validos


def gerar_cards(texto: str, quantidade: int, user_id: int, db: Session) -> list[dict]:
    """
    Chama o Gemini e devolve uma lista de dicts: [{"front": ..., "back": ...}].
    Lança IAError se algo der errado.
    """
    bruto = _chamar_ia(_montar_prompt(texto, quantidade), user_id, db, timeout=20)

    try:
        cards = json.loads(_limpar_json(bruto))
    except json.JSONDecodeError as e:
        raise IAError("A IA não devolveu um JSON válido") from e

    # Valida o formato e fica só com o que tem front e back.
    validos = [
        {"front": str(c["front"]), "back": str(c["back"])}
        for c in cards
        if isinstance(c, dict) and "front" in c and "back" in c
    ]
    if not validos:
        raise IAError("A IA não gerou nenhum card válido")

    return validos
