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
"""
from sqlalchemy.orm import Session

from app.services.ai import IAError, _chamar_ia  # noqa: F401 (IAError reexportado p/ quem importar daqui)

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
