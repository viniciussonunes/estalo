"""
Schemas do usuário — os "formulários" de entrada e saída da API.

Repara na diferença entre eles: o que ENTRA tem senha, o que SAI nunca tem.
Isso é de propósito: a senha nunca volta pro mundo, nem embaralhada.
"""
from datetime import datetime

from pydantic import BaseModel


class UserCreate(BaseModel):
    """O que o usuário manda no cadastro."""
    email: str
    password: str


class PasswordChange(BaseModel):
    """Troca de senha de quem já está logado.

    Pede a senha atual mesmo com o token na mão: token roubado (aparelho
    esquecido aberto, sessão vazada) não pode virar posse da conta. Sem essa
    confirmação, quem pegasse o crachá trocaria a senha e trancaria o dono
    do lado de fora -- e, como não existe recuperação de senha, seria
    definitivo.
    """
    senha_atual: str
    senha_nova: str


class UserOut(BaseModel):
    """O que a API devolve sobre um usuário. Sem senha, nunca."""
    id: int
    email: str
    created_at: datetime

    # Permite o Pydantic ler direto de um objeto do banco (o model User).
    model_config = {"from_attributes": True}
