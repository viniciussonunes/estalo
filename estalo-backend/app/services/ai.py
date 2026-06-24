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

import httpx

from app.core.config import settings

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


class IAError(Exception):
    """Erro ao falar com a IA (chave faltando, API fora do ar, resposta estranha)."""


def _montar_prompt(texto: str, quantidade: int) -> str:
    """Instrui o Gemini a virar o texto em cards e responder SÓ com JSON."""
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
    if not settings.GEMINI_API_KEY:
        raise IAError(
            "Chave do Gemini não configurada. Preencha GEMINI_API_KEY no arquivo .env"
        )

    url = GEMINI_URL.format(model=settings.GEMINI_MODEL)
    payload = {"contents": [{"parts": [{"text": _montar_prompt_quiz(cards)}]}]}
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": settings.GEMINI_API_KEY,
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=90)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise IAError(f"Gemini respondeu com erro {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise IAError(f"Falha ao conectar no Gemini: {e}") from e

    try:
        dados = resp.json()
        bruto = dados["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise IAError("Resposta do Gemini veio em formato inesperado") from e

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
    if not settings.GEMINI_API_KEY:
        raise IAError(
            "Chave do Gemini não configurada. Preencha GEMINI_API_KEY no arquivo .env"
        )

    url = GEMINI_URL.format(model=settings.GEMINI_MODEL)
    payload = {"contents": [{"parts": [{"text": _montar_prompt_revelar(cards)}]}]}
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": settings.GEMINI_API_KEY,
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=90)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise IAError(f"Gemini respondeu com erro {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise IAError(f"Falha ao conectar no Gemini: {e}") from e

    try:
        dados = resp.json()
        bruto = dados["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise IAError("Resposta do Gemini veio em formato inesperado") from e

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


def gerar_cards(texto: str, quantidade: int) -> list[dict]:
    """
    Chama o Gemini e devolve uma lista de dicts: [{"front": ..., "back": ...}].
    Lança IAError se algo der errado.
    """
    if not settings.GEMINI_API_KEY:
        raise IAError(
            "Chave do Gemini não configurada. Preencha GEMINI_API_KEY no arquivo .env"
        )

    url = GEMINI_URL.format(model=settings.GEMINI_MODEL)
    payload = {
        "contents": [
            {"parts": [{"text": _montar_prompt(texto, quantidade)}]}
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": settings.GEMINI_API_KEY,
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise IAError(f"Gemini respondeu com erro {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise IAError(f"Falha ao conectar no Gemini: {e}") from e

    # Extrai o texto que a IA gerou de dentro da resposta do Gemini.
    try:
        dados = resp.json()
        bruto = dados["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise IAError("Resposta do Gemini veio em formato inesperado") from e

    # Converte o texto (que deve ser JSON) em lista de dicts.
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
