"""
ImportStagingCard — pouso temporário dos cards extraídos de um .apkg antes
de virarem Card/Review de verdade (Motor de Importação Anki).

POST /import/anki (futuro) grava aqui logo depois do parse, sem tocar em
Card/Review ainda. POST /import/anki/{job_id}/process-batch (futuro)
promove daqui pra lá em lotes. É isso que garante que um import que falha
no meio nunca deixa Card pela metade nas tabelas de verdade — o rollback é
só apagar as linhas de staging daquele job_id.
"""
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base


class ImportStagingCard(Base):
    __tablename__ = "import_staging"

    id:     Mapped[int] = mapped_column(Integer, primary_key=True)
    # UUID gerado por POST /import/anki — ainda não é FK pra uma tabela de
    # jobs (essa não existe nesta etapa), só agrupa as linhas de um mesmo import.
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    front: Mapped[str]        = mapped_column(Text, nullable=False)
    back:  Mapped[str]        = mapped_column(Text, nullable=False)
    tags:  Mapped[str | None] = mapped_column(Text, nullable=True)  # string bruta do Anki (espaço-separado); sem mapeamento pro Estalo ainda

    # Metadados crus do Anki (ease, ivl, reps, due, queue, type, note_type...)
    # que a etapa de promoção usa pra montar o Review — ver mapeamento
    # planejado em services/anki_mapping.py (ainda não implementado).
    anki_payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    status:        Mapped[str]        = mapped_column(String(16), nullable=False, default="pending")  # pending | processed | error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
