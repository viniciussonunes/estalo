"""
Serviço de IA — gera cards a partir de um texto, usando o Gemini.

A ideia (sua dor #1): você entrega um texto de estudo e a IA devolve pares
pergunta/resposta prontos. O "monitor" (Gemini) lê suas anotações e cria as
perguntas de revisão.

Decisão importante: pedimos a resposta em JSON ESTRUTURADO, não texto solto.
Assim o código lê com segurança, sem adivinhar onde acaba a pergunta e começa
a resposta. É a diferença entre receber um formulário preenchido e um bilhete
escrito à mão.
"""
import json
import time

import httpx

from app.core.config import settings

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


class IAError(Exception):
    """Erro ao falar com a IA (chave faltando, API fora do ar, resposta estranha)."""


_RETRY_STATUS = {429, 500, 502, 503, 504}


def _chamar_gemini(prompt: str, timeout: int = 25, instrucao_sistema: str | None = None) -> str:
    """Chama o Gemini e retorna o texto gerado. Tenta até 2 vezes em erros transitórios.

    Orçamento de tempo pensado pra caber numa função serverless: 2 tentativas
    de até `timeout`s cada, com 2s de espera entre elas — pior caso
    ~2*timeout + 2s. Antes eram 3 tentativas de até 90s com backoff 2s/4s
    (pior caso ~276s), o que estourava qualquer limite de duração de função
    plausível bem antes da 3ª tentativa terminar.

    `instrucao_sistema`, quando informado, vai no campo `systemInstruction` da
    própria API — separado de `contents` de propósito. É o que faz a persona
    (tom, regras, formatação) ficar estável entre chamadas, sem competir com o
    conteúdo específico de cada prompt nem precisar ser reforçada em cada um.
    """
    if not settings.GEMINI_API_KEY:
        raise IAError("Chave do Gemini não configurada. Preencha GEMINI_API_KEY no arquivo .env")

    url = GEMINI_URL.format(model=settings.GEMINI_MODEL)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
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
        f"3. 'distractors': Lista de EXATAMENTE 3 alternativas INCORRETAS que sejam:\n"
        f"   - Plausíveis e relacionadas especificamente a ESTA pergunta\n"
        f"   - Geradas de forma exclusiva para este card (NUNCA copie o 'back' de outros cards)\n"
        f"   - Distintas entre si e da resposta correta\n"
        f"4. 'explanation': Explicação de 2-3 frases explicando POR QUÊ a resposta correta está certa.\n\n"
        f"Regras gerais:\n"
        f"- Use o idioma do texto.\n"
        f"- Responda APENAS com um array JSON válido, sem texto antes ou depois, sem markdown.\n"
        f'- Formato exato: [{{"front":"...","back":"...","distractors":["...","...","..."],"explanation":"..."}}]\n\n'
        f"TEXTO:\n{texto}"
    )


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
        "3. Crie EXATAMENTE 3 alternativas INCORRETAS ('distractors') que sejam:\n"
        "   - Plausíveis e contextualizadas para AQUELA pergunta específica\n"
        "   - Geradas exclusivamente para esse card (NUNCA copie o 'back' de outros cards)\n"
        "   - Distintas entre si e distintas da resposta correta\n"
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


def gerar_quiz(cards: list[dict]) -> list[dict]:
    """
    Recebe lista de {card_id, front, back} e devolve lista de
    {card_id, question, correct, distractors, explanation}.
    Lança IAError se algo der errado.
    """
    bruto = _chamar_gemini(_montar_prompt_quiz(cards))

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
        validos.append({
            "card_id": int(item["card_id"]),
            "question": str(item["question"]),
            "correct": str(item["correct"]),
            "distractors": [str(d) for d in distractors[:3]],
            "explanation": str(item["explanation"]),
        })

    if not validos:
        raise IAError("A IA não gerou questões válidas")

    return validos


def gerar_explicacoes(cards: list[dict]) -> list[dict]:
    """
    Recebe lista de {card_id, front, back} e devolve lista de
    {card_id, explanation}.
    Lança IAError se algo der errado.
    """
    bruto = _chamar_gemini(_montar_prompt_revelar(cards))

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


def gerar_cards_completos(texto: str, quantidade: int) -> list[dict]:
    """
    Gera cards com front, back, distractors e explanation em uma única chamada.
    Retorna lista de dicts com todas as chaves preenchidas.
    """
    bruto = _chamar_gemini(_montar_prompt_completo(texto, quantidade), timeout=30)

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
        validos.append({
            "front":        str(c["front"]),
            "back":         str(c["back"]),
            "distractors":  [str(d) for d in distractors[:3]],
            "explanation":  str(c["explanation"]),
        })

    if not validos:
        raise IAError("A IA não gerou cards válidos com a estrutura completa")

    return validos


def gerar_cards(texto: str, quantidade: int) -> list[dict]:
    """
    Chama o Gemini e devolve uma lista de dicts: [{"front": ..., "back": ...}].
    Lança IAError se algo der errado.
    """
    bruto = _chamar_gemini(_montar_prompt(texto, quantidade), timeout=20)

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
