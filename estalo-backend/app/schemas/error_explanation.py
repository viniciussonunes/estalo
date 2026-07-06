from pydantic import BaseModel, Field


class ExplanationRequest(BaseModel):
    alternativa_escolhida: str = Field(..., min_length=1, max_length=500)


class ExplanationOut(BaseModel):
    explanation: str
    versao: int
    # True só quando o teto de refinamentos (MAX_VERSAO, ver
    # error_explanation_service.py) já foi atingido -- a explicação
    # devolvida é a última válida, não uma nova tentativa.
    limite_atingido: bool = False


class ExplanationFeedbackRequest(BaseModel):
    alternativa_escolhida: str = Field(..., min_length=1, max_length=500)
    positivo: bool
    # Obrigatório só quando positivo=False (validado no service/endpoint,
    # não aqui via Field -- Pydantic não expressa bem "obrigatório se X").
    motivo: str | None = Field(None, max_length=2000)
