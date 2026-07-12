"""
Challenge — desafios de estudo assistidos por IA, em tabela paralela a
cards (não mexe em Card/CardOut/nada do fluxo de estudo de TI do app).

Nasceu como protótipo genérico (multi-tipo, content livre em JSON) e hoje
hospeda também o Mentor de Inglês Ativo (type="ENGLISH_TUTOR", o default
-- ver challenge_service.py pro prompt específico). Mesma tabela, mesmo
motor de geração/persistência pros dois usos -- só o system prompt muda
por `type`.

Se o experimento não vingar, o rollback é DROP TABLE challenges; nenhuma
tabela existente referencia esta aqui, então apagar é seguro e não deixa
nada órfão.

Sem relationship de volta em Deck (back_populates) de propósito -- reduz a
superfície tocada em models/deck.py a zero, mantendo o motor de estudos
de TI do resto do app isolado das regras de negócio daqui (e vice-versa).
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id"), nullable=False, index=True)

    # "ENGLISH_TUTOR" é o default (ver ChallengeGenerateRequest) -- o
    # Mentor de Inglês Ativo é o caso de uso principal hoje. Sem
    # enum/constraint de banco de propósito: tipos novos não devem exigir
    # migração.
    type: Mapped[str] = mapped_column(String, nullable=False, default="ENGLISH_TUTOR")

    # Payload livre por tipo (JSON). Pra ENGLISH_TUTOR:
    # {student_attempt, native_correction, why, collocations}. Outros
    # tipos (FILL_THE_GAP, MULTIPLE_CHOICE, TRUE_FALSE...) têm shape próprio
    # -- ver _EXEMPLOS_POR_TIPO em challenge_service.py.
    content: Mapped[dict] = mapped_column(JSON, nullable=False)

    explanation:       Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    tutor_explanation: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    # Nível CEFR (A1-C2) do desafio -- só populado pra tipos de idioma
    # (ENGLISH_TUTOR hoje); None pros demais tipos, que não têm essa noção.
    language_level: Mapped[str | None] = mapped_column(String(2), nullable=True, default=None)

    # func.now() (expressão SQL avaliada pelo banco no INSERT), não
    # datetime.utcnow -- diferente do resto do projeto de propósito nesta
    # tabela experimental. default= (não server_default=), então só é
    # aplicado quando o INSERT passa pelo SQLAlchemy (ver preview_only em
    # challenge_service.gerar_challenge, que nunca chega a persistir).
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    deck: Mapped["Deck"] = relationship()
