"""
Schemas do Motor de Importação Anki.
"""
from pydantic import BaseModel


class ImportJobOut(BaseModel):
    job_id: str


class ImportProgressOut(BaseModel):
    processed: int
    total: int
    errors: int
