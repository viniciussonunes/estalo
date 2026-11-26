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
     sair em pedaços (ver MAX_SEGUNDOS_POR_BLOCO em tts.py).
  2. De uso: 5 minutos de conversa sem índice é um bloco opaco -- ninguém
     acha "carbapenêmicos" arrastando a barra no escuro. Cada bloco tem
     título e vira um capítulo navegável.

Como os dois querem o mesmo corte, o roteiro já nasce picado no tamanho
certo. O título não é enfeite: é o que o pedaço custa a mais por existir,
e é o que paga a navegação.
"""
import json
import math
import re
import time

from sqlalchemy.orm import Session

from app.services.ai import IAError, _chamar_ia, _limpar_json
from app.services.tts import (
    CHARS_POR_SEGUNDO, MAX_SEGUNDOS_POR_BLOCO, PAUSA_PARA_PENSAR_S, VOZ_HOMEM, VOZ_MULHER,
)

# Dois locutores fixos. Nomes próprios (e não "Locutor A/B") porque o
# modelo de TTS usa o nome pra manter a voz consistente, e porque um
# roteiro com nome de gente sai mais natural do que um com rótulo.
QUEM_PERGUNTA = "Rafael"   # voz masculina -- puxa a dúvida, faz o papel de quem estuda
QUEM_EXPLICA = "Beatriz"   # voz feminina  -- explica, faz o papel de quem já sabe
LOCUTORES = (QUEM_PERGUNTA, QUEM_EXPLICA)

# Explícito, e não "quem falar primeiro fica com a voz masculina": essa
# regra padrão de tts.sintetizar trocava as vozes em todo bloco que
# começava com Beatriz -- ela saía com a voz do Rafael e vice-versa.
VOZES = {QUEM_PERGUNTA: VOZ_HOMEM, QUEM_EXPLICA: VOZ_MULHER}

# Uma fala de "Hmm, deixa eu pensar" passa disto? Então não é a fala de
# ganhar tempo que o prompt pede, e a pausa vai logo depois da pergunta.
MAX_CHARS_FALA_DE_ESPERA = 80

# A pausa ocupa tempo de áudio como texto ocuparia -- conta no tamanho do
# bloco (limite técnico) e na posição estimada dos capítulos na tela.
CHARS_DA_PAUSA = int(PAUSA_PARA_PENSAR_S * CHARS_POR_SEGUNDO)

# Teto de um bloco (= um capítulo = um POST de gravação). Quem garante é
# _dividir_bloco_longo abaixo, que corta o que passar -- o prompt pede um
# tamanho, o código impõe. A IA escreve ~1100 caracteres por bloco seja
# qual for o pedido (medido na fase 2, pedindo em caracteres e em
# falas), então o teto está onde a técnica permite, não onde o pedido
# estava: ver MAX_SEGUNDOS_POR_BLOCO em tts.py.
CHARS_MAX_POR_BLOCO = int(MAX_SEGUNDOS_POR_BLOCO * CHARS_POR_SEGUNDO)  # ~1080

MIN_BLOCOS, MAX_BLOCOS = 3, 10

# O tamanho do bloco é pedido em FALAS, não em caracteres: a IA não sabe
# contar caracteres. Medido com o prompt da fase 2 pedindo caracteres:
# vinham 2-3x o pedido e o corte automático picava metade dos blocos em
# capítulos "(continuação)". 6-8 falas de até duas frases (~90
# caracteres) dão os ~650 caracteres do alvo.
FALAS_POR_BLOCO = (6, 8)

# Teto de pensamento do Gemini pro roteiro (ver _chamar_gemini_raw).
# Medido: pensamento livre levava 23-80s (o teto da função é 50s);
# zero respondia em 9s mas escrevia sem plano; 512, 10-13s.
ORCAMENTO_THINKING = 512

INSTRUCAO = (
    "Você escreve roteiros de áudio para estudo. Seu trabalho é transformar "
    "flashcards numa conversa entre duas pessoas que soa natural ao ouvido, "
    "nunca numa leitura de lista nem num interrogatório."
)


# Um bloco a cada 2 cards. Era 3 na fase 1; a fase 2 gasta ~25% mais
# texto por conceito (erro, pergunta pra quem ouve, pausa -- medido nos
# protótipos: 2085 -> 2574 e 1890 -> 2127 caracteres), e com 3 a IA
# estourava o tamanho e o corte automático picava os blocos em
# capítulos "(continuação)".
CARDS_POR_BLOCO = 2


def _quantos_blocos(total_cards: int) -> int:
    return max(MIN_BLOCOS, min(MAX_BLOCOS, round(total_cards / CARDS_POR_BLOCO) or MIN_BLOCOS))


def _montar_prompt(deck_titulo: str, cards: list[dict], blocos: int) -> str:
    """O prompt da fase 2 (escolhido em 2026-11-25 sobre protótipos A x C).

    O diagnóstico, em 11 roteiros de produção da fase 1: Rafael lia a
    frente do card ("qual a principal função de X?"), Beatriz carimbava
    ("Exato!" em 38% das falas), ninguém errava, e o fecho comentava a
    própria conversa ("cobrimos o essencial"). Ouvir era escutar.

    O que muda é o MATERIAL: o card do Estalo já guarda as alternativas
    erradas do quiz e a explicação. Com elas, o erro do Rafael é a
    confusão que o próprio quiz testa (não uma que a IA inventa) e o
    porquê da Beatriz vem da explicação (não de enchimento genérico).
    E uma vez por bloco a pergunta vai pra quem ouve, com pausa real
    depois (ver PAUSA_PARA_PENSAR_S) -- é o que transforma o áudio em
    revisão ativa, que é o que o resto do app faz.
    """
    R, B = QUEM_PERGUNTA, QUEM_EXPLICA
    entrada = [
        {
            "pergunta": c["front"],
            "resposta": c["back"],
            "confusoes_comuns": c.get("distractors") or [],
            "por_que": c.get("explanation") or "",
        }
        for c in cards
    ]
    return (
        f'Transforme os flashcards do deck "{deck_titulo}" numa conversa de estudo '
        f"entre {R} e {B}. Quem ouve está REVISANDO esse conteúdo: a conversa existe "
        "para fazer a pessoa puxar da memória, não só escutar.\n\n"
        "O MATERIAL: cada card traz a resposta certa e, quando houver, as "
        "'confusoes_comuns' (respostas erradas plausíveis, as mesmas do quiz do app) "
        "e o 'por_que' da resposta certa.\n\n"
        "OS PERSONAGENS:\n"
        f"- {R} está estudando e já viu o assunto uma vez. Às vezes pergunta, mas muitas "
        "vezes ARRISCA a resposta antes de ouvir. Fala frases curtas.\n"
        f"- {B} domina o assunto. Explica o porquê, e às vezes devolve a pergunta para "
        f"{R} em vez de responder direto.\n\n"
        "TRÊS MOMENTOS QUE A CONVERSA PRECISA TER:\n"
        "A. ERRO QUE ENSINA: NO MÁXIMO UM por bloco, e nunca na primeira fala da "
        f"conversa. {R} arrisca uma resposta ERRADA tirada das 'confusoes_comuns' daquele "
        "card, com convicção e com as palavras dele. No resto do tempo ele acerta ou "
        f"pergunta: ele estudou, só não domina. {B} corrige sem dar NENHUMA razão parcial "
        "ao erro (nada de \"isso também conta\", \"é uma parte\"): diz o que está "
        "errado, por que a confusão é tentadora e qual é a diferença, usando o 'por_que'.\n"
        f"B. ACERTO QUE AVANÇA: quando {R} acerta, {B} não elogia nem confirma com uma "
        "palavra solta; acrescenta a camada seguinte (consequência, exceção, ligação com "
        "outro card).\n"
        f"C. VEZ DE QUEM OUVE: uma vez por bloco, {B} lança uma pergunta NOVA direto para "
        "quem está ouvindo (\"E você aí: por que ...?\"). Marque essa fala com "
        '"para_quem_ouve": true. Ela é feita uma vez só: ninguém a fez antes nem a repete '
        f"depois. A fala seguinte é de {R}, curta, ganhando tempo (\"Hmm... deixa eu "
        "pensar nessa.\"), e a fala depois dela já traz a resposta completa. Não explique "
        "a técnica nem diga que é uma pausa.\n\n"
        "ESTRUTURA:\n"
        f"1. Divida a conversa em EXATAMENTE {blocos} blocos. Cada bloco é um trecho "
        "contínuo da MESMA conversa, não um episódio separado.\n"
        "2. Cada bloco tem um 'titulo' curto (3 a 6 palavras) que diz o assunto daquele "
        "trecho. Vira um capítulo navegável: descritivo, nunca genérico; maiúscula só na "
        "primeira palavra e em nomes próprios. Bom: \"Resistência: betalactamases\". "
        "Ruim: \"Continuação\", \"Parte 2\".\n"
        f"3. Cada bloco tem de {FALAS_POR_BLOCO[0]} a {FALAS_POR_BLOCO[1]} falas. Cada fala "
        "tem no máximo duas frases curtas; só a correção de um erro pode chegar a três.\n"
        "4. As falas alternam entre os dois. Nunca duas falas seguidas da mesma pessoa.\n\n"
        "ABERTURA E FECHAMENTO:\n"
        "5. A primeira fala do primeiro bloco situa quem ouve: diz de que assunto é a "
        "conversa e o que vem pela frente, em uma ou duas frases, de jeito natural.\n"
        "6. O último bloco termina com uma recapitulação curta das duas ou três ideias que "
        "mais importam, dita como conversa. PROIBIDO comentar a própria conversa: nada de "
        "\"cobrimos\", \"vimos hoje\", \"ficou de fora\", \"o essencial foi coberto\", "
        "\"fechamos o ciclo\".\n\n"
        "NATURALIDADE:\n"
        f"7. Os nomes são só \"{R}\" e \"{B}\". Sem apelidos. Ninguém diz o próprio nome. "
        "Chamar o outro pelo nome no máximo uma vez na conversa inteira.\n"
        "8. Nenhuma fala começa com concordância automática: \"Exato\", \"Exatamente\", "
        "\"Isso mesmo\", \"Perfeito\", \"Precisamente\", \"Correto\", \"Entendi\", "
        "\"Certo\", \"Ok\", \"Isso\", \"Sim\", \"Boa pergunta\", \"Excelente pergunta\". "
        "Quando um concorda com o outro, mostra que concorda ACRESCENTANDO algo, não "
        "carimbando.\n"
        f"9. {R} não lê a pergunta do card. Ninguém fala \"qual a analogia para entender "
        "X\" ou \"qual a principal função de Y\". As dúvidas dele nascem do que acabou de "
        "ser dito: uma consequência, um caso concreto, uma comparação com o anterior.\n"
        "10. Cada analogia aparece UMA vez. Se já usou, siga sem ela.\n"
        "11. Nada de frase de enchimento que não diz nada (\"otimizando o fluxo de "
        "trabalho\", \"de forma eficiente e intuitiva\"). Toda frase carrega informação.\n\n"
        "CONTEÚDO:\n"
        "12. Use só o que está nos cards. Não invente fatos, números ou exemplos técnicos "
        "que os cards não sustentam. Se forem muitos cards para o tempo, priorize os "
        "conceitos centrais, em silêncio, sem anunciar o que ficou de fora.\n"
        "13. Escreva para o OUVIDO: sem marcadores, sem numeração, sem siglas não "
        "explicadas, sem \"como vimos no card anterior\". Números e símbolos por extenso.\n"
        "14. Use o mesmo idioma dos flashcards.\n\n"
        "Responda APENAS com JSON válido, sem markdown, no formato exato:\n"
        '{"blocos": [{"titulo": "...", "falas": [{"quem": "' + R + '", "texto": "..."}, '
        '{"quem": "' + B + '", "texto": "...", "para_quem_ouve": true}]}]}\n\n'
        f"FLASHCARDS:\n{json.dumps(entrada, ensure_ascii=False, indent=2)}"
    )


def _tamanho(fala: dict) -> int:
    """Quanto a fala ocupa de áudio, em caracteres -- a pausa conta."""
    return len(fala["texto"]) + (CHARS_DA_PAUSA if fala.get("pausa") else 0)


def tamanho_do_bloco(falas: list[dict]) -> int:
    return sum(_tamanho(f) for f in falas)


def _unidades(falas: list[dict]) -> list[list[dict]]:
    """Agrupa as falas em trechos que não podem ser separados.

    A pergunta pra quem ouve, a fala de espera, a pausa e a resposta são
    um momento só: cortado no meio, a pergunta fecha um capítulo e a
    resposta abre o seguinte -- e quem pula de capítulo cai na resposta
    sem a pergunta. Toda outra fala é uma unidade sozinha.
    """
    unidades: list[list[dict]] = []
    atual: list[dict] = []
    for f in falas:
        atual.append(f)
        # A unidade fica aberta enquanto a última fala for a pergunta ou
        # a fala com pausa -- a resposta ainda precisa entrar nela.
        if not (f.get("para_quem_ouve") or f.get("pausa")):
            unidades.append(atual)
            atual = []
    if atual:
        unidades.append(atual)
    # Unidade que sozinha passa do teto não cabe em capítulo nenhum: aí
    # cortar dentro dela é o mal menor -- estourar o teto é estourar o
    # limite de resposta da função, e o bloco inteiro se perde.
    return [
        u2 for u in unidades
        for u2 in ([u] if tamanho_do_bloco(u) <= CHARS_MAX_POR_BLOCO else [[f] for f in u])
    ]


def _dividir_bloco_longo(falas: list[dict]) -> list[list[dict]]:
    """Parte um bloco que veio acima do limite técnico, em pedaços iguais.

    A IA erra o tamanho pra cima com frequência, e um bloco grande demais
    faria a síntese recusar o pedaço inteiro (ver sintetizar()). O corte
    cai sempre numa troca de fala, que é uma pausa natural -- e nunca no
    meio de uma pergunta pra quem ouve (ver _unidades).

    Por que pedaços IGUAIS e não "encher até estourar": encher deixava um
    rabo minúsculo no fim -- medido, um bloco de 889 caracteres virava
    690 + 199, e esses 199 viravam um capítulo de 11 segundos chamado
    "(continuação)" na tela. Dividir pelo número de pedaços necessários
    dá dois capítulos de tamanho parecido, ambos justificando a própria
    linha na lista.
    """
    total = tamanho_do_bloco(falas)
    unidades = _unidades(falas)
    if total <= CHARS_MAX_POR_BLOCO or len(unidades) < 2:
        return [falas]

    quantos = math.ceil(total / CHARS_MAX_POR_BLOCO)
    alvo = total / quantos

    pedacos: list[list[dict]] = []
    atual: list[dict] = []
    tamanho = 0
    for unidade in unidades:
        tam_unidade = tamanho_do_bloco(unidade)
        # Fecha o pedaço quando já passou do alvo, ou quando esta unidade
        # o levaria além do teto. A segunda condição é o que GARANTE o
        # teto: nenhum pedaço com mais de uma unidade passa dele. (Uma
        # versão anterior só cortava "se sobrassem unidades pros pedaços
        # restantes", e o último pedaço juntava a sobra: 1134 caracteres
        # vistos em teste, ~3,9 MB de PCM, no limite da resposta.)
        if atual and (tamanho >= alvo or tamanho + tam_unidade > CHARS_MAX_POR_BLOCO):
            pedacos.append(atual)
            atual, tamanho = [], 0
        atual.extend(unidade)
        tamanho += tam_unidade
    if atual:
        pedacos.append(atual)
    return pedacos


# Carimbo de concordância no começo da fala: "Exato!", "Isso mesmo.",
# "Perfeito,". O prompt proíbe e a IA obedece só às vezes -- 38% das
# falas da Beatriz em produção, e voltou numa rodada de teste já com a
# proibição. Arrancar no código é determinístico: só sai quando há texto
# depois, então uma fala que é SÓ "Certo." fica como está.
_CARIMBO = re.compile(
    r"^(?:exatamente|exato|isso mesmo|isso|perfeito|precisamente|correto|certo|"
    r"entendi|ok|sim|boa pergunta|excelente pergunta)\s*[!.,]+\s*",
    re.IGNORECASE,
)


def _tirar_carimbo(texto: str) -> str:
    resto = _CARIMBO.sub("", texto, count=1)
    if not resto or resto == texto:
        return texto
    return resto[0].upper() + resto[1:]


def _fundir_falas_seguidas(falas: list[dict]) -> list[dict]:
    """Duas falas seguidas da mesma pessoa viram uma.

    O prompt proíbe, e a IA faz mesmo assim (visto no protótipo). No
    áudio, a mesma voz parando e recomeçando soa como corte de edição.
    """
    fundidas: list[dict] = []
    for f in falas:
        if fundidas and fundidas[-1]["quem"] == f["quem"]:
            ultima = fundidas[-1]
            ultima["texto"] = f"{ultima['texto']} {f['texto']}"
            ultima["para_quem_ouve"] = ultima.get("para_quem_ouve") or f.get("para_quem_ouve")
        else:
            fundidas.append(dict(f))
    return fundidas


# "Hmm... deixa eu pensar nessa." no começo de uma fala do Rafael que
# segue com a resposta dele. A pausa tem que cair ENTRE a hesitação e a
# resposta; colada, ela cairia antes do "Hmm" (visto em teste real).
#
# Só a hesitação EXPLÍCITA conta ("deixa eu pensar", "essa eu sei"). Um
# "Hmm," solto é só jeito de falar: visto em teste, Beatriz perguntou pro
# Rafael, ele respondeu "Hmm, a característica comum? Acho que..." e um
# padrão que aceitava "Hmm" sozinho pôs 3s de silêncio no meio da frase.
_HESITACAO = re.compile(
    r"^((?:(?:hmm+|humm+|hum)[\s.…,!]*)?deixa eu pensar(?: nessa| um pouco)?[\s.…,!]*"
    r"|(?:(?:hmm+|humm+|hum)[\s.…,!]*)?espera[\s.…,!]*essa eu sei[\s.…,!]*)",
    re.IGNORECASE,
)


def _separar_hesitacao(falas: list[dict], i: int) -> None:
    """Se falas[i] é "Hmm... <resposta>", vira duas falas no lugar."""
    texto = falas[i]["texto"]
    m = _HESITACAO.match(texto)
    if not m:
        return
    # Sem exigir resto no padrão: assim ele casa a hesitação INTEIRA
    # ("Hmm... deixa eu pensar nessa.") em vez de encolher pra sobrar um
    # "nessa." de resto. Só divide se o que sobra é resposta de verdade.
    hesitacao, resto = texto[:m.end()].strip(), texto[m.end():].strip()
    if not any(ch.isalnum() for ch in resto):
        return
    falas[i] = {**falas[i], "texto": hesitacao}
    falas.insert(i + 1, {"quem": falas[i]["quem"], "texto": resto})


# Jeitos que a IA usa pra se virar pra quem ouve. Ela escreve a pergunta
# mas nem sempre marca "para_quem_ouve" (visto: "E você aí: ...?" e "Para
# quem está ouvindo: ...?", os dois sem a marca, ou seja, sem pausa).
_CHAMADO_A_QUEM_OUVE = re.compile(r"\b(você aí|quem (está|tá) ouvindo|quem ouve)\b", re.IGNORECASE)


def _e_pergunta_pra_quem_ouve(falas: list[dict], i: int) -> bool:
    """Reconhece a pergunta pra quem ouve pelo texto, sem depender da marca.

    Dois sinais, qualquer um basta, sempre numa fala da Beatriz com "?":
    ela chama quem ouve ("você aí", "quem está ouvindo"), ou a fala
    seguinte é o Rafael hesitando ("Hmm... deixa eu pensar") -- que é o
    formato que o prompt pede pra esse momento e só pra ele.
    """
    f = falas[i]
    if f["quem"] != QUEM_EXPLICA or "?" not in f["texto"]:
        return False
    if _CHAMADO_A_QUEM_OUVE.search(f["texto"]):
        return True
    seguinte = falas[i + 1] if i + 1 < len(falas) else None
    return bool(seguinte and seguinte["quem"] == QUEM_PERGUNTA and _HESITACAO.match(seguinte["texto"]))


def _marcar_pausas(falas: list[dict]) -> list[dict]:
    """Decide onde entra o silêncio de cada pergunta pra quem ouve.

    O desenho é pergunta -> "Hmm, deixa eu pensar" do Rafael -> silêncio
    -> resposta. A fala de espera avisa que o silêncio é de propósito;
    silêncio logo depois da pergunta soaria como áudio travado. Se a IA
    não escreveu a fala de espera (ou escreveu uma fala de conteúdo), a
    pausa vai logo depois da pergunta mesmo: melhor travado-parecendo do
    que sem tempo pra pensar.

    A pergunta só vale como pergunta pra quem ouve se depois dela vier
    uma resposta; marcada na última fala do bloco, é descartada -- a
    resposta estaria em outro capítulo.
    """
    for i, f in enumerate(falas):
        if not f.get("para_quem_ouve") and not _e_pergunta_pra_quem_ouve(falas, i):
            continue
        f["para_quem_ouve"] = True
        if i + 1 < len(falas) and falas[i + 1]["quem"] == QUEM_PERGUNTA:
            _separar_hesitacao(falas, i + 1)
        seguinte = falas[i + 1] if i + 1 < len(falas) else None
        if seguinte is None:
            f.pop("para_quem_ouve", None)
            continue
        e_espera = (seguinte["quem"] == QUEM_PERGUNTA
                    and len(seguinte["texto"]) <= MAX_CHARS_FALA_DE_ESPERA
                    and i + 2 < len(falas))
        (seguinte if e_espera else f)["pausa"] = True
    return falas


def _validar(dados: dict) -> list[dict]:
    """Converte a resposta crua em blocos confiáveis, ou explode.

    Tudo que vem da IA é tratado como suspeito: tipo errado, locutor
    inventado, bloco vazio, bloco gigante. O que dá pra consertar sem
    adivinhar (bloco longo, locutor com capitalização diferente, falas
    seguidas da mesma pessoa) é consertado; o resto vira erro, porque
    gerar áudio de um roteiro quebrado custa dinheiro e tempo pra
    entregar lixo.

    Cada fala sai como {"quem", "texto"} e, onde entra o silêncio pra
    quem ouve pensar, "pausa": true. Roteiros da fase 1 não têm a chave
    e continuam valendo -- só não têm pausa.
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

        falas: list[dict] = []
        for f in falas_cruas:
            if not isinstance(f, dict):
                continue
            quem = conhecidos.get(str(f.get("quem") or "").strip().lower())
            texto = _tirar_carimbo(str(f.get("texto") or "").strip())
            if quem and texto:
                falas.append({"quem": quem, "texto": texto,
                              "para_quem_ouve": f.get("para_quem_ouve") is True})

        if not falas:
            continue

        falas = _marcar_pausas(_fundir_falas_seguidas(falas))

        for i, pedaco in enumerate(_dividir_bloco_longo(falas)):
            blocos.append({
                "titulo": titulo,
                # Pedaço cortado de um bloco longo: é outro POST de gravação,
                # mas o MESMO capítulo pra quem ouve (ver _resumo no router).
                # Antes virava um capítulo "(continuação)" na lista -- 6 de 39
                # na fase 1, metade na fase 2 antes desta marca.
                **({"continua": True} if i > 0 else {}),
                "falas": [
                    {"quem": f["quem"], "texto": f["texto"], **({"pausa": True} if f.get("pausa") else {})}
                    for f in pedaco
                ],
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

    `cards` é [{"front", "back", "distractors"?, "explanation"?}]: as
    alternativas erradas e a explicação são o material do erro do Rafael
    e do porquê da Beatriz. Uma chamada só de texto --
    o áudio vem depois, bloco a bloco, porque é ele que não cabe no
    tempo de uma função.
    """
    if not cards:
        raise IAError("Deck sem cards para narrar")

    prompt = _montar_prompt(deck_titulo, cards, _quantos_blocos(len(cards)))

    # Duas tentativas dentro do mesmo orçamento de tempo: ~1 em 6 respostas
    # vinha com o JSON quebrado (medido), e com ~12s por chamada cabe uma
    # segunda sem passar do teto da função. Cada tentativa passa pela cota.
    inicio = time.monotonic()
    ultimo_erro: IAError | None = None
    for _ in range(2):
        restante = int(timeout - (time.monotonic() - inicio))
        if restante < 20:
            break
        bruto = _chamar_ia(
            prompt,
            user_id=user_id,
            db=db,
            timeout=restante,
            instrucao_sistema=INSTRUCAO,
            orcamento_thinking=ORCAMENTO_THINKING,
        )
        try:
            return _validar(json.loads(_limpar_json(bruto)))
        except json.JSONDecodeError as e:
            ultimo_erro = IAError("A IA respondeu o roteiro num formato inesperado")
            ultimo_erro.__cause__ = e
        except IAError as e:
            ultimo_erro = e
    raise ultimo_erro or IAError("Sem tempo para escrever o roteiro")
