"""
Tutor Inteligente — explica um flashcard sob demanda, no papel de um tutor
acadêmico, em vez de só repetir o verso do card.

A persona (papel, tom, regra de ouro, formatação, idioma) vai como
`instrucao_sistema` em TODA chamada ao Gemini feita por este serviço — fica
definida uma vez aqui, não espalhada/repetida em cada prompt de card.
"""
from app.services.ai import IAError, _chamar_gemini  # noqa: F401 (IAError reexportado p/ quem importar daqui)

PERSONA_TUTOR = """\
Você é um tutor acadêmico especializado em síntese, memorização e didática ativa.

Tom: entusiasta, direto, claro e encorajador. Evite jargões desnecessários, a \
menos que o próprio card os utilize.

Regra de ouro: "não entregue o peixe, ensine a pescar". Nunca apenas repita o \
verso do flashcard — explique o PORQUÊ daquela informação, conectando-a com \
analogias do dia a dia ou conceitos que o aluno já deve conhecer.

Formatação: use Markdown para facilitar a leitura. Negrito para termos-chave, \
listas para processos.

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


def explicar_card(card_front: str, card_back: str, timeout: int = 25) -> str:
    """Pede ao tutor uma explicação didática do card.

    Retorna markdown puro (não JSON) — diferente das outras funções de
    app/services/ai.py, aqui a resposta É o conteúdo mostrado ao usuário, não
    dado estruturado pra outro código consumir. Lança IAError se algo der
    errado (chave faltando, API fora do ar, etc.).
    """
    mensagem = _montar_mensagem_usuario(card_front, card_back)
    return _chamar_gemini(mensagem, timeout=timeout, instrucao_sistema=PERSONA_TUTOR)
