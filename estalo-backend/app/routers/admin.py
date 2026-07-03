"""
Endpoints de diagnóstico operacional — não fazem parte do domínio do app,
existem só pra dar visibilidade de infra sem precisar acessar credenciais
diretamente (ex: confirmar qual host de banco está em uso).

Protegidos por um token simples (DIAGNOSTIC_TOKEN). Sem o token configurado,
o endpoint responde 404 — nunca fica aberto por falta de configuração.
"""
import secrets

from fastapi import APIRouter, Header, HTTPException, status

from app.core.config import settings
from app.core.database import engine

router = APIRouter(prefix="/admin", tags=["Admin"])


def _autorizado(token_recebido: str | None) -> bool:
    if not settings.DIAGNOSTIC_TOKEN:
        return False
    return secrets.compare_digest(token_recebido or "", settings.DIAGNOSTIC_TOKEN)


@router.get("/debug/db")
def debug_db(x_diagnostic_token: str | None = Header(None, alias="X-Diagnostic-Token")):
    """
    Devolve só o hostname da conexão de banco em uso — nunca usuário/senha.
    Serve pra confirmar de fora se a app está usando o endpoint "-pooler"
    do Neon (DATABASE_URL_POOL) ou a conexão direta (DATABASE_URL).
    """
    if not _autorizado(x_diagnostic_token):
        # 404, não 401/403: não revela nem que a rota existe pra quem não
        # tem o token.
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    return {
        "host": engine.url.host,
        "usando_pool": bool(settings.DATABASE_URL_POOL),
    }
