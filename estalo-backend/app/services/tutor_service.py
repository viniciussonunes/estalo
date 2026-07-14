"""
Tutor Inteligente — explica um flashcard sob demanda, no papel de um tutor
acadêmico, em vez de só repetir o verso do card.

A persona (papel, tom, regra de ouro, formatação, idioma) vai como
`instrucao_sistema` em TODA chamada ao Gemini feita por este serviço — fica
definida uma vez aqui, não espalhada/repetida em cada prompt de card.

Nota de arquitetura: a chamada de verdade passa por _chamar_ia
(app/services/ai.py) -- o Adaptador de provedor de IA (Gemini/OpenAI). Este
serviço não sabe qual dos dois está por trás; só monta a persona/mensagem e
delega. Pro Gemini especificamente, a persona vai no campo `systemInstruction`
do payload REST cru (não via SDK `google-generativeai`), o conteúdo do card
vai em `contents` -- os dois nunca se misturam num prompt só.

Três capacidades neste módulo, cada uma com persona própria (nunca
reaproveitam PERSONA_TUTOR entre si -- são tons/formatos diferentes de
propósito, misturar quebraria o contrato de cada uma):

1. explicar_card() -- Tutor Inteligente completo (até 2 parágrafos,
   markdown, cacheado em Card.tutor_explanation). Usado pelo modal
   "Perguntar ao Tutor" do Modo Aprender (POST /study/cards/{id}/tutor).
2. explicar_conceito_breve() -- versão curta (≤3 frases, texto puro, SEM
   cache) pro botão "Explicar" do Modo Revelar (POST /cards/{id}/tutor,
   ver routers/cards.py) -- pensada pra não quebrar o fluxo de quem está
   revelando cards em sequência.
3. analisar_feedback() -- classifica o tipo de erro de uma tentativa de
   resposta (omissão/imprecisão/erro conceitual) e identifica o "gap
   cognitivo" por trás dele antes de explicar. Preparação de motor pra
   uma futura tela que capture a tentativa do usuário -- ainda sem
   endpoint/UI ligados a ela nesta sprint.
"""
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.ai import IAError, _chamar_ia, _limpar_json  # noqa: F401 (IAError reexportado p/ quem importar daqui)

# Modelo dedicado do Tutor: mais rápido/barato que o padrão usado por
# gerar_cards/gerar_quiz (settings.GEMINI_MODEL) -- resposta sob demanda
# durante o estudo é sensível a latência de um jeito que geração em lote não
# é. Fica isolado aqui, não em settings, pra não afetar as outras features.
# Só se aplica ao Gemini -- a OpenAI usa sempre OPENAI_MODEL (ver ai.py).
#
# "gemini-1.5-flash" (pedido originalmente) não existe mais -- a API
# responde 404 (confirmado direto contra GET /v1beta/models com a chave de
# produção). A linha 1.5 foi descontinuada; "gemini-2.5-flash-lite" é o
# equivalente atual (variante lite do modelo já usado em gerar_cards/
# gerar_quiz), mais leve/rápida que a 2.5-flash padrão sem trocar de geração.
TUTOR_MODEL = "gemini-2.5-flash-lite"

PERSONA_TUTOR = """\
Você é um tutor acadêmico especializado em síntese, memorização e didática ativa.

Tom: entusiasta, direto, claro e encorajador. Evite jargões desnecessários, a \
menos que o próprio card os utilize.

Regra de ouro: "não entregue o peixe, ensine a pescar". Nunca apenas repita o \
verso do flashcard — explique o PORQUÊ daquela informação, conectando-a com \
analogias do dia a dia ou conceitos que o aluno já deve conhecer.

Formatação: use Markdown para facilitar a leitura. Negrito para termos-chave, \
listas para processos.

Seja conciso. Resposta máxima de 2 parágrafos. Use listas para detalhamentos \
e prefira explicações diretas. Mantenha o tom entusiasta.

Se o conteúdo do card for ambíguo ou muito técnico sem contexto, peça \
gentilmente para o usuário fornecer um pouco mais de detalhes, ou pergunte \
qual parte específica do conceito está travando o aprendizado dele.

Idioma: responda estritamente no idioma do card (se o card está em \
português, responda em português)."""


def _montar_mensagem_usuario(card_front: str, card_back: str) -> str:
    return (
        "Você está estudando o conceito abaixo:\n"
        "---\n"
        f"[Front do Card]: {card_front}\n"
        f"[Back do Card]: {card_back}\n"
        "---\n"
        "O usuário pediu ajuda para entender este conteúdo. Siga as diretrizes "
        "de tutor acima e forneça uma explicação clara e memorável."
    )


def explicar_card(card_front: str, card_back: str, user_id: int, db: Session, timeout: int = 25) -> str:
    """Pede ao tutor uma explicação didática do card.

    Retorna markdown puro (não JSON) — diferente das outras funções de
    app/services/ai.py, aqui a resposta É o conteúdo mostrado ao usuário, não
    dado estruturado pra outro código consumir. Lança IAError (ou
    QuotaExceededError, ver ai.py) se algo der errado (chave faltando, API
    fora do ar, cota diária estourada, etc.).
    """
    mensagem = _montar_mensagem_usuario(card_front, card_back)
    return _chamar_ia(
        mensagem, user_id, db, timeout=timeout, instrucao_sistema=PERSONA_TUTOR, model=TUTOR_MODEL,
    )


# --- Botão "Explicar" (Modo Revelar) -------------------------------------

PERSONA_EXPLICACAO_BREVE = """\
Você é um tutor que dá explicações RÁPIDAS de conceitos, pensadas pra não \
quebrar o fluxo de quem está estudando com flashcards -- a pessoa acabou de \
revelar a resposta e quer só um empurrão extra de entendimento, não uma aula.

Regra de ouro, inegociável: no MÁXIMO 3 frases. Mesmo que o conceito seja \
complexo, escolha o ângulo mais útil de aprofundar e vá direto a ele -- \
nunca liste múltiplos pontos, escolha UM.

Tom -- decida pelo CONTEÚDO do card, nunca pergunte:
- Se for aprendizado de idioma (vocabulário, gramática, expressões): tom \
pedagógico e encorajador, como um professor de idiomas incentivando o aluno.
- Se for conteúdo técnico (TI, programação, conceitos técnicos em geral): \
tom técnico e direto, sem rodeios, como um mentor sênior revisando algo com \
um colega.

Formatação: pode usar **negrito** (markdown) pra destacar o termo-chave do \
conceito -- só isso, sem listas, sem títulos, é só um parágrafo curto com \
no máximo uma ou duas palavras/expressões em negrito, as mais importantes \
pra quem for só bater o olho.

Idioma: responda no idioma do card."""


def _montar_mensagem_explicacao_breve(card_front: str, card_back: str) -> str:
    return (
        "O aluno acabou de revelar a resposta deste flashcard:\n"
        "---\n"
        f"[Frente]: {card_front}\n"
        f"[Verso]: {card_back}\n"
        "---\n"
        "Dê uma explicação rápida (máximo 3 frases) que aprofunde o "
        "entendimento do conceito por trás da resposta -- não repita o "
        "verso, vá além dele."
    )


def explicar_conceito_breve(
    card_front: str, card_back: str, user_id: int, db: Session, timeout: int = 20,
) -> str:
    """Versão curta de explicar_card(), pro botão "Explicar" do Modo
    Revelar -- ver POST /cards/{id}/tutor em routers/cards.py.

    Diferenças deliberadas em relação a explicar_card(): resposta em
    texto puro (não markdown, nada renderiza isso inline), teto de 3
    frases (não 2 parágrafos), e SEM cache -- cada clique gera de novo.
    Isso é uma escolha consciente pra esta sprint (o endpoint já se
    declara "simplificado"): se o custo de gerações repetidas pro mesmo
    card virar problema, o próximo passo natural é um campo de cache
    dedicado (não reaproveitar Card.tutor_explanation, que guarda a
    versão longa de explicar_card() -- misturar as duas quebraria uma ou
    a outra na próxima leitura).
    """
    mensagem = _montar_mensagem_explicacao_breve(card_front, card_back)
    return _chamar_ia(
        mensagem, user_id, db, timeout=timeout,
        instrucao_sistema=PERSONA_EXPLICACAO_BREVE, model=TUTOR_MODEL,
    )


# --- Análise de tentativa de resposta (preparação de motor) --------------
#
# Ainda sem endpoint/UI -- ver docstring do módulo. Existe pra já deixar a
# classificação de erro testável e pronta antes de uma tela que capture a
# tentativa do usuário existir de verdade.

_TIPOS_ERRO_VALIDOS = {"omissao", "imprecisao", "erro_conceitual"}

PERSONA_ANALISE_FEEDBACK = """\
Você é um tutor que analisa a tentativa de resposta de um aluno antes de \
explicar o que ele errou -- não corrige só "certo/errado", entende O TIPO \
de erro primeiro.

Passo 1 -- CLASSIFIQUE o erro em exatamente uma destas três categorias:
- "omissao": o aluno deixou de mencionar uma parte importante da resposta \
correta, mas o que ele disse não está errado, só incompleto.
- "imprecisao": o aluno chegou perto do conceito certo, mas usou termos \
vagos, incompletos ou levemente equivocados.
- "erro_conceitual": o aluno demonstra um entendimento fundamentalmente \
errado do conceito, não apenas uma resposta incompleta ou imprecisa.

Passo 2 -- identifique o "gap cognitivo": a lacuna de entendimento \
ESPECÍFICA por trás do erro. Não repita a resposta correta aqui -- nomeie \
o que exatamente o aluno não entendeu (ex: "confunde causa com efeito", \
"não distingue os dois conceitos", "aplica a regra geral onde há uma \
exceção").

Passo 3 -- escreva uma explicação curta (máximo 3 frases) corrigindo o \
erro, com o TOM ajustado ao assunto (decida pelo contexto, nunca pergunte):
- Aprendizado de idioma (vocabulário, gramática, expressões): tom \
pedagógico e encorajador.
- Conteúdo técnico (TI, programação, conceitos técnicos em geral): tom \
técnico e direto, sem rodeios.
Pode destacar o termo-chave do conceito em **negrito** (markdown) dentro \
do texto de "explicacao" -- só uma ou duas palavras/expressões, as mais \
importantes pra quem for só bater o olho.

Responda com um objeto JSON válido, sem texto antes ou depois do objeto \
em si, sem ```envolver o JSON``` em bloco de código, com EXATAMENTE estas \
três chaves (o **negrito** do passo 3 acima vai DENTRO do valor de
"explicacao", isso não conflita com o JSON em si continuar válido):
- "tipo_erro": "omissao" | "imprecisao" | "erro_conceitual"
- "gap_cognitivo": string curta (1 frase) nomeando a lacuna específica
- "explicacao": string (máximo 3 frases), no tom adequado ao assunto"""


def _montar_prompt_analise_feedback(user_attempt: str, correct_answer: str, context: str) -> str:
    return (
        "Analise a tentativa de resposta do aluno abaixo.\n"
        "---\n"
        f"[Contexto/Pergunta]: {context}\n"
        f"[Resposta correta]: {correct_answer}\n"
        f"[O que o aluno respondeu]: {user_attempt}\n"
        "---\n"
        "Siga os 3 passos das diretrizes acima: classifique o erro, "
        "identifique o gap cognitivo, e gere a explicação no tom "
        "adequado ao assunto."
    )


@dataclass
class AnaliseFeedback:
    tipo_erro: str        # "omissao" | "imprecisao" | "erro_conceitual"
    gap_cognitivo: str
    explicacao: str


def analisar_feedback(
    user_attempt: str, correct_answer: str, context: str, user_id: int, db: Session, timeout: int = 25,
) -> AnaliseFeedback:
    """Classifica o erro numa tentativa de resposta (omissão/imprecisão/
    erro conceitual), identifica o gap cognitivo por trás dele, e gera
    uma explicação curta no tom adequado ao assunto (pedagógico pra
    idioma, técnico pra TI) -- tudo numa ÚNICA chamada de IA: a
    classificação sai como o primeiro campo do JSON estruturado
    devolvido, "antes" da explicação no mesmo sentido que o raciocínio
    de um LLM sobre saída estruturada é sequencial campo a campo, não
    porque são duas chamadas separadas (duas chamadas dobrariam custo/
    latência sem ganho real aqui).

    Lança IAError se a IA não devolver JSON válido ou classificar o erro
    fora das 3 categorias esperadas -- nunca deixa um `tipo_erro`
    inventado vazar pra quem chama.
    """
    bruto = _chamar_ia(
        _montar_prompt_analise_feedback(user_attempt, correct_answer, context),
        user_id, db, timeout=timeout, instrucao_sistema=PERSONA_ANALISE_FEEDBACK,
    )

    try:
        dados = json.loads(_limpar_json(bruto))
    except json.JSONDecodeError as e:
        raise IAError("A IA não devolveu um JSON válido") from e

    if not isinstance(dados, dict):
        raise IAError("A IA não devolveu um objeto JSON")

    tipo_erro = dados.get("tipo_erro")
    if tipo_erro not in _TIPOS_ERRO_VALIDOS:
        raise IAError(f"A IA classificou o erro com um tipo inesperado: {tipo_erro!r}")

    gap_cognitivo = dados.get("gap_cognitivo")
    explicacao = dados.get("explicacao")
    if not gap_cognitivo or not explicacao:
        raise IAError("A IA não devolveu gap_cognitivo/explicacao válidos")

    return AnaliseFeedback(
        tipo_erro=tipo_erro, gap_cognitivo=str(gap_cognitivo), explicacao=str(explicacao),
    )
