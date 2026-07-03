"""
A "catraca" do prédio.

get_current_user é a função que protege os endpoints. Ela:
1. Pega o crachá (token) que veio no cabeçalho da requisição
2. Lê quem é o usuário
3. Busca ele no banco
4. Se algo falhar, barra a entrada (erro 401)

Qualquer endpoint que quiser ser "só pra logado" é só pedir essa dependência.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User

# Diz ao FastAPI: o crachá chega via login no endpoint /auth/login.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


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
