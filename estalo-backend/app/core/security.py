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
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"


# ---------- Senha ----------
def hash_password(senha: str) -> str:
    """Embaralha a senha pra guardar no banco. Sentido único: não dá pra voltar."""
    # bcrypt trabalha com bytes e tem limite de 72 bytes por senha.
    # Desde services/password_policy.py, senha maior que isso é RECUSADA na
    # entrada em vez de cortada em silêncio -- este corte virou só uma
    # última linha de defesa. O corte no verify_password abaixo, ao
    # contrário, precisa continuar existindo: senhas gravadas antes da
    # regra podem ter passado dos 72 bytes, e quem tem uma delas ainda
    # precisa conseguir entrar.
    senha_bytes = senha.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(senha_bytes, salt).decode("utf-8")


def verify_password(senha: str, hash_guardado: str) -> bool:
    """Confere se a senha digitada bate com o hash guardado."""
    senha_bytes = senha.encode("utf-8")[:72]
    return bcrypt.checkpw(senha_bytes, hash_guardado.encode("utf-8"))


# ---------- Token JWT ----------
def create_access_token(subject: str, token_version: int = 1) -> str:
    """Cria o crachá. 'subject' é o id do usuário, que vai dentro do token.

    `token_version` é a geração de crachás daquele usuário. Trocar a senha
    incrementa a geração no banco, e aí todo crachá emitido antes para de
    valer -- é assim que uma sessão aberta em outro aparelho cai."""
    # datetime.utcnow() está deprecated; o equivalente não-deprecated é
    # datetime.now(timezone.utc), mas isso devolve um datetime AWARE — e
    # todo o resto do projeto assume naive-UTC (colunas DateTime sem
    # timezone=True, comparações diretas com valores vindos do banco).
    # .replace(tzinfo=None) descarta a tzinfo, preservando o MESMO valor
    # que utcnow() já devolvia, sem arriscar TypeError de "naive vs aware"
    # em nenhuma comparação existente.
    expira_em = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expira_em, "ver": token_version}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Lê o crachá e devolve o id do usuário. Se for inválido/expirado, devolve None."""
    dados = ler_token(token)
    return dados[0] if dados else None


def ler_token(token: str) -> tuple[str, int] | None:
    """(id do usuário, geração do crachá), ou None se inválido/expirado.

    `ver` ausente vira 1: crachás emitidos ANTES de o campo existir
    continuam valendo, senão o deploy desta mudança deslogaria todo mundo
    de uma vez (ver token_version em models/user.py)."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    sub = payload.get("sub")
    if sub is None:
        return None
    try:
        versao = int(payload.get("ver", 1))
    except (TypeError, ValueError):
        versao = 1
    return sub, versao
