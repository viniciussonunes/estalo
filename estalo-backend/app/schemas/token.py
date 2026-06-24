"""
Schema do token — o formato do "crachá" que a API devolve no login.
"""
from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
