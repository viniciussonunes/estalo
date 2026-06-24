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


class UserOut(BaseModel):
    """O que a API devolve sobre um usuário. Sem senha, nunca."""
    id: int
    email: str
    created_at: datetime

    # Permite o Pydantic ler direto de um objeto do banco (o model User).
    model_config = {"from_attributes": True}
