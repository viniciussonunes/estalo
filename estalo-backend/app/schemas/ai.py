"""
Schemas da geração de cards por IA.
"""
from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    # max_length pensado pra cobrir "um artigo/uma página ou duas" (ver
    # Leitura em Inglês abaixo) sem deixar uma geração custar uma fatia
    # grande demais da cota diária de tokens (Quota Manager) numa
    # chamada só -- 12.000 chars ~ 3.000 tokens de entrada, ~6% da cota
    # padrão (50.000/dia). Vale pros dois usos deste schema (geração
    # genérica de flashcard e leitura em inglês), não só o de inglês.
    text: str = Field(min_length=10, max_length=12_000)  # o texto de estudo
    quantity: int = Field(default=5, ge=1, le=30)  # quantos cards gerar

    # --- Leitura em Inglês (ver app/services/ai.py:gerar_cards_leitura_ingles) ---
    # language_level presente é o que ativa esse modo -- ausente (None,
    # default), o endpoint continua gerando flashcard genérico como
    # sempre. Não é um schema separado de propósito: mesmo endpoint,
    # mesmo formato de card gerado (front/back/distractors/explanation),
    # só o prompt por trás muda.
    language_level: str | None = Field(None, pattern="^(A1|A2|B1|B2|C1|C2)$")
    # Idioma de back+explanation juntos (nunca misturado) -- front fica
    # sempre em inglês, é o trecho real do texto sendo treinado. Só é
    # efetivamente usado quando language_level está presente.
    answer_language: str = Field("pt", pattern="^(pt|en)$")
