"""
Segurança: criptografia de senha + tokens JWT.

Duas responsabilidades aqui:
1. Senha: nunca guardamos a senha real. Guardamos um "hash" (uma versão
   embaralhada e irreversível). Mesmo se alguém roubar o banco, não consegue
   ler as senhas.
2. Token JWT: depois do login, o usuário recebe um "crachá" assinado. Em cada
   requisição ele mostra o crachá, e a gente confere a assinatura sem precisar
   consultar o banco toda hora.
"""
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"


# ---------- Senha ----------
def hash_password(senha: str) -> str:
    """Embaralha a senha pra guardar no banco. Sentido único: não dá pra voltar."""
    # bcrypt trabalha com bytes e tem limite de 72 bytes por senha.
    senha_bytes = senha.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(senha_bytes, salt).decode("utf-8")


def verify_password(senha: str, hash_guardado: str) -> bool:
    """Confere se a senha digitada bate com o hash guardado."""
    senha_bytes = senha.encode("utf-8")[:72]
    return bcrypt.checkpw(senha_bytes, hash_guardado.encode("utf-8"))


# ---------- Token JWT ----------
def create_access_token(subject: str) -> str:
    """Cria o crachá. 'subject' é o id do usuário, que vai dentro do token."""
    expira_em = datetime.utcnow() + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expira_em}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Lê o crachá e devolve o id do usuário. Se for inválido/expirado, devolve None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
