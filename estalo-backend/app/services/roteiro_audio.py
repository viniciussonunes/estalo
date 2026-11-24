"""
Roteirista — transforma os cards de um deck num diálogo entre duas pessoas,
dividido em blocos que viram capítulos na tela de Ouvir.

--- Por que diálogo, e não narração ---
Narração vira leitura de lista: "pergunta, resposta, pergunta, resposta".
Um diálogo obriga o texto a ter PORQUÊ -- alguém pergunta, alguém explica,
alguém confere se entendeu. É a diferença entre ouvir um glossário e ouvir
uma monitoria.

--- Por que blocos ---
Dois motivos que por acaso pedem a mesma coisa:
  1. Técnico: a geração de áudio roda a ~2,2x o tempo real e o maxDuration
     da Vercel é 60s. Um episódio de 5 min não cabe numa chamada; precisa
     sair em pedaços (ver MAX_SEGUNDOS_POR_PEDACO em tts.py).
  2. De uso: 5 minutos de conversa sem índice é um bloco opaco -- ninguém
     acha "carbapenêmicos" arrastando a barra no escuro. Cada bloco tem
     título e vira um capítulo navegável.

Como os dois querem o mesmo corte, o roteiro já nasce picado no tamanho
certo. O título não é enfeite: é o que o pedaço custa a mais por existir,
e é o que paga a navegação.
"""
import json
import math

from sqlalchemy.orm import Session

from app.services.ai import IAError, _chamar_ia, _limpar_json
from app.services.tts import CHARS_POR_SEGUNDO, MAX_SEGUNDOS_POR_PEDACO

# Dois locutores fixos. Nomes próprios (e não "Locutor A/B") porque o
# modelo de TTS usa o nome pra manter a voz consistente, e porque um
# roteiro com nome de gente sai mais natural do que um com rótulo.
QUEM_PERGUNTA = "Rafael"   # voz masculina -- puxa a dúvida, faz o papel de quem estuda
QUEM_EXPLICA = "Beatriz"   # voz feminina  -- explica, faz o papel de quem já sabe
LOCUTORES = (QUEM_PERGUNTA, QUEM_EXPLICA)

# ~45s de áudio por bloco: capítulo de tamanho navegável, e com folga
# contra o teto técnico. O alvo é um PEDIDO ao modelo e ele erra pra
# cima com frequência (medido: pedi 900, veio 1138). Quem garante de
# verdade é _dividir_bloco_longo abaixo, que corta o que passar do
# máximo -- o prompt pede, o código impõe.
CHARS_ALVO_POR_BLOCO = int(45 * CHARS_POR_SEGUNDO)      # ~648
CHARS_MAX_POR_BLOCO = int(MAX_SEGUNDOS_POR_PEDACO * CHARS_POR_SEGUNDO)  # ~864

MIN_BLOCOS, MAX_BLOCOS = 3, 10

INSTRUCAO = (
    "Você escreve roteiros de áudio para estudo. Seu trabalho é transformar "
    "flashcards numa conversa entre duas pessoas que soa natural ao ouvido, "
    "nunca numa leitura de lista."
)


def _quantos_blocos(total_cards: int) -> int:
    return max(MIN_BLOCOS, min(MAX_BLOCOS, round(total_cards / 3) or MIN_BLOCOS))


def _montar_prompt(deck_titulo: str, cards: list[dict], blocos: int) -> str:
    cards_json = json.dumps(cards, ensure_ascii=False, indent=2)
    return (
        f'Transforme os flashcards do deck "{deck_titulo}" numa conversa de estudo '
        f"entre {QUEM_PERGUNTA} e {QUEM_EXPLICA}.\n\n"
        "OS PERSONAGENS:\n"
        f"- {QUEM_PERGUNTA} está estudando. Ele puxa as dúvidas, pede exemplo, "
        "confere se entendeu, às vezes erra e é corrigido. Fala frases curtas.\n"
        f"- {QUEM_EXPLICA} já domina o assunto. Ela explica com clareza, dá o "
        "porquê das coisas e conecta um tópico ao seguinte. Fala frases médias.\n\n"
        "REGRAS OBRIGATÓRIAS:\n"
        f"1. Divida a conversa em EXATAMENTE {blocos} blocos. Cada bloco é um "
        "trecho contínuo da MESMA conversa, não um episódio separado.\n"
        f"2. Cada bloco tem um 'titulo' curto (3 a 6 palavras) que diz o assunto "
        "daquele trecho. Esse título vira um capítulo navegável -- precisa "
        "descrever o conteúdo, não ser genérico, e usar maiúscula só na "
        "primeira palavra e em nomes próprios. Bom: \"Resistência: "
        "betalactamases\". Ruim: \"Continuação\", \"Parte 2\", "
        "\"Mecanismo E Resistência\".\n"
        f"3. Cada bloco deve ter entre {CHARS_ALVO_POR_BLOCO - 150} e "
        f"{CHARS_ALVO_POR_BLOCO + 150} caracteres somando todas as falas. "
        f"NUNCA passe de {CHARS_MAX_POR_BLOCO} caracteres num bloco.\n"
        "4. As falas alternam entre os dois. Nunca duas falas seguidas da "
        "mesma pessoa.\n"
        f"5. O primeiro bloco abre a conversa (quem está falando, sobre o quê). "
        "O último fecha amarrando o que foi visto.\n"
        "6. Cubra o conteúdo dos cards. Se forem muitos para o tempo, priorize "
        "os conceitos centrais e diga em voz alta o que ficou de fora.\n"
        "7. Escreva para o OUVIDO: sem marcadores, sem numeração, sem "
        "siglas não explicadas, sem 'como vimos no card anterior'. Números e "
        "símbolos por extenso (\"cinquenta por cento\", não \"50%\").\n"
        "8. Use o mesmo idioma dos flashcards.\n\n"
        "Responda APENAS com JSON válido, sem markdown, no formato exato:\n"
        '{"blocos": [{"titulo": "...", "falas": [{"quem": "' + QUEM_PERGUNTA +
        '", "texto": "..."}, {"quem": "' + QUEM_EXPLICA + '", "texto": "..."}]}]}\n\n'
        f"FLASHCARDS:\n{cards_json}"
    )


def _dividir_bloco_longo(falas: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Parte um bloco que veio acima do limite técnico, em pedaços iguais.

    A IA erra o tamanho pra cima com frequência, e um bloco grande demais
    faria a síntese recusar o pedaço inteiro (ver sintetizar()). O corte
    cai sempre numa troca de fala, que é uma pausa natural.

    Por que pedaços IGUAIS e não "encher até estourar": encher deixava um
    rabo minúsculo no fim -- medido, um bloco de 889 caracteres virava
    690 + 199, e esses 199 viravam um capítulo de 11 segundos chamado
    "(continuação)" na tela. Dividir pelo número de pedaços necessários
    dá dois capítulos de tamanho parecido, ambos justificando a própria
    linha na lista.
    """
    total = sum(len(t) for _, t in falas)
    if total <= CHARS_MAX_POR_BLOCO or len(falas) < 2:
        return [falas]

    quantos = math.ceil(total / CHARS_MAX_POR_BLOCO)
    alvo = total / quantos

    pedacos: list[list[tuple[str, str]]] = []
    atual: list[tuple[str, str]] = []
    tamanho = 0
    for i, (quem, texto) in enumerate(falas):
        faltam_falas = len(falas) - i
        faltam_pedacos = quantos - len(pedacos)
        # Fecha o pedaço quando já passou do alvo, desde que ainda sobrem
        # falas suficientes pra encher os pedaços restantes.
        if atual and tamanho >= alvo and faltam_pedacos > 1 and faltam_falas >= faltam_pedacos:
            pedacos.append(atual)
            atual, tamanho = [], 0
        atual.append((quem, texto))
        tamanho += len(texto)
    if atual:
        pedacos.append(atual)
    return pedacos


def _validar(dados: dict) -> list[dict]:
    """Converte a resposta crua em blocos confiáveis, ou explode.

    Tudo que vem da IA é tratado como suspeito: tipo errado, locutor
    inventado, bloco vazio, bloco gigante. O que dá pra consertar sem
    adivinhar (bloco longo, locutor com capitalização diferente) é
    consertado; o resto vira erro, porque gerar áudio de um roteiro
    quebrado custa dinheiro e tempo pra entregar lixo.
    """
    if not isinstance(dados, dict) or not isinstance(dados.get("blocos"), list):
        raise IAError("Roteiro veio sem a lista de blocos")

    conhecidos = {q.lower(): q for q in LOCUTORES}
    blocos: list[dict] = []

    for cru in dados["blocos"]:
        if not isinstance(cru, dict):
            continue
        titulo = str(cru.get("titulo") or "").strip()
        falas_cruas = cru.get("falas")
        if not titulo or not isinstance(falas_cruas, list):
            continue

        falas: list[tuple[str, str]] = []
        for f in falas_cruas:
            if not isinstance(f, dict):
                continue
            quem = conhecidos.get(str(f.get("quem") or "").strip().lower())
            texto = str(f.get("texto") or "").strip()
            if quem and texto:
                falas.append((quem, texto))

        if not falas:
            continue

        for i, pedaco in enumerate(_dividir_bloco_longo(falas)):
            blocos.append({
                "titulo": titulo if i == 0 else f"{titulo} (continuação)",
                "falas": [{"quem": q, "texto": t} for q, t in pedaco],
            })

    if not blocos:
        raise IAError("Roteiro veio vazio")
    return blocos


def gerar_roteiro(
    deck_titulo: str,
    cards: list[dict],
    user_id: int,
    db: Session,
    timeout: int = 50,
) -> list[dict]:
    """Devolve [{titulo, falas: [{quem, texto}]}] pronto pra virar áudio.

    `cards` é [{"front": ..., "back": ...}]. Uma chamada só de texto --
    o áudio vem depois, bloco a bloco, porque é ele que não cabe no
    tempo de uma função.
    """
    if not cards:
        raise IAError("Deck sem cards para narrar")

    prompt = _montar_prompt(deck_titulo, cards, _quantos_blocos(len(cards)))
    bruto = _chamar_ia(
        prompt,
        user_id=user_id,
        db=db,
        timeout=timeout,
        instrucao_sistema=INSTRUCAO,
    )

    try:
        dados = json.loads(_limpar_json(bruto))
    except json.JSONDecodeError as e:
        raise IAError("A IA respondeu o roteiro num formato inesperado") from e

    return _validar(dados)
