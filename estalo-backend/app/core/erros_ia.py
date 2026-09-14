"""
Tradução de IAError pra resposta HTTP -- uma frase calma pro usuário, o
detalhe técnico só no log.

Motivo: seis endpoints faziam `raise HTTPException(502, str(e))`, e o
str(e) era escrito pra desenvolvedor: "A IA não devolveu um JSON válido",
"Gemini indisponível após 2 tentativas (...)", "Falha ao conectar no
Gemini: ...", "Chave do Gemini não configurada. Preencha GEMINI_API_KEY
no arquivo .env". Isso chegava inteiro na tela de quem tinha acabado de
colar as anotações pra virar cards. Nada disso é acionável por quem
estuda -- a única coisa que a pessoa pode fazer é tentar de novo daqui a
pouco, então é isso que a mensagem diz.

O detalhe continua existindo: vai pro stdout (print, como o resto da
telemetria do projeto -- é o que a Vercel captura sem configuração de
logging), com um `contexto` que diz qual operação falhou.

QuotaExceededError é a exceção: a mensagem dela já foi escrita pro
usuário ("Limite diário ... Tente novamente amanhã") e o frontend precisa
do 429 pra abrir o modal de cota, então passa intacta.
"""
from fastapi import HTTPException, status

from app.services.ai import IAError, QuotaExceededError

MENSAGEM_IA_INDISPONIVEL = "A IA não conseguiu responder agora. Tente de novo em instantes."


def erro_http_de_ia(e: IAError, contexto: str) -> HTTPException:
    if isinstance(e, QuotaExceededError):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
    print(f"[ia_indisponivel] contexto={contexto} erro={e!r}")
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, MENSAGEM_IA_INDISPONIVEL)
