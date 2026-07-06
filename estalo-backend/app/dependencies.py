"""
A "catraca" do prédio.

get_current_user é a função que protege os endpoints. Ela:
1. Pega o crachá (token) que veio no cabeçalho da requisição
2. Lê quem é o usuário
3. Busca ele no banco
4. Se algo falhar, barra a entrada (erro 401)

Qualquer endpoint que quiser ser "só pra logado" é só pedir essa dependência.
"""
from zoneinfo import ZoneInfo, available_timezones

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User

# Diz ao FastAPI: o crachá chega via login no endpoint /auth/login.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Calculado uma vez no import (não a cada request) — available_timezones()
# varre a base de fusos do sistema operacional.
_TIMEZONES_VALIDAS = available_timezones()


def get_user_timezone(
    x_user_timezone: str | None = Header(None, alias="X-User-Timezone"),
) -> ZoneInfo:
    """Fuso horário do usuário, mandado pelo frontend a cada request (ver
    api.js — Intl.DateTimeFormat().resolvedOptions().timeZone). Usado só
    pra calcular fronteiras de "dia" (streak, crítico/hoje, elegibilidade
    de resposta) — o armazenamento continua sempre UTC, isso nunca entra
    no banco.

    Sem header ou com valor que não bate com nenhum fuso IANA conhecido,
    cai pra UTC — mais seguro que travar a request (clientes antigos,
    testes automatizados e chamadas diretas à API não mandam esse header).
    """
    if x_user_timezone and x_user_timezone in _TIMEZONES_VALIDAS:
        return ZoneInfo(x_user_timezone)
    return ZoneInfo("UTC")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    erro = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Crachá inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user_id = decode_access_token(token)
    if user_id is None:
        raise erro

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise erro

    return user


def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    """Versão leve de get_current_user: só decodifica e valida o JWT, SEM
    consultar o banco. Use nos endpoints que só precisam do id pra filtrar
    queries (a grande maioria) — evita um SELECT redundante em toda
    request, já que o próprio token já é uma prova criptográfica válida da
    identidade.

    Trade-off consciente: se o usuário for excluído do banco, um token
    dele ainda dentro da validade (7 dias) continua sendo aceito aqui — a
    request só falharia se tentasse usar um recurso que realmente não
    existe mais (ex: dono de um deck). Hoje o app não tem endpoint de
    exclusão de conta, então isso não acontece na prática. Se um dia
    existir "excluir minha conta", reavaliar esse trade-off (ex: invalidar
    tokens ativos no logout/exclusão).

    Pra rotas que precisam dos dados de verdade do usuário (email, etc.),
    use get_current_user — ex: GET /auth/me.
    """
    erro = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Crachá inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user_id = decode_access_token(token)
    if user_id is None:
        raise erro

    return int(user_id)


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Catraca extra pros endpoints de /admin/* (gestão de cotas).

    O pedido original dizia só "protegido por autenticação" -- mas isso
    sozinho deixaria QUALQUER usuário cadastrado listar e alterar a cota
    de todo mundo (GET /admin/users devolve dados de todos, PATCH altera
    o limite de qualquer user_id). Pra uma rota assim, "logado" não é
    proteção suficiente -- é preciso ser especificamente um admin.

    ADMIN_EMAILS (settings) é a lista de quem pode entrar, separada por
    vírgula; vazio por padrão (ninguém entra até configurar). Comparação
    é feita contra o email do token decodificado, não algo vindo do
    cliente -- não dá pra forjar.
    """
    admins = {e.strip().lower() for e in settings.ADMIN_EMAILS.split(",") if e.strip()}
    if user.email.lower() not in admins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito a administradores")
    return user
