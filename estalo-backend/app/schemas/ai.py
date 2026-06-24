"""
Schemas da geração de cards por IA.
"""
from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    text: str = Field(min_length=10)        # o texto de estudo
    quantity: int = Field(default=5, ge=1, le=30)  # quantos cards gerar
