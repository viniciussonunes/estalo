"""
DeckAudio — o roteiro de áudio de um deck (tela "Ouvir").

Guarda o ROTEIRO (texto), não o áudio. O MP3 mora no aparelho de quem
ouviu, no Cache API do navegador. Dois motivos:

  1. Áudio é caro de guardar e barato de regerar a partir do roteiro --
     o inverso do que o senso comum sugere. O que custou IA foi escrever
     o diálogo; a locução é um passo determinístico em cima dele.
  2. Guardar o roteiro é o que permite RETOMAR. A tela promete "se sair,
     o que já foi gravado fica salvo e você continua de onde parou"; sem
     o roteiro no servidor, voltar significaria pagar a IA de novo só
     pra reescrever a mesma conversa.

Guardar os bytes do áudio no servidor é a fase 3 do plano (vale a pena
quando a mesma pessoa ouve em mais de um aparelho).

`content_hash` é o retrato dos cards no momento em que o roteiro nasceu.
Quando ele não bate mais com o deck, o áudio está falando de uma versão
antiga do conteúdo -- é isso que acende o aviso "este áudio está
atrasado" na tela, em vez de deixar a pessoa estudar por um áudio que
não corresponde mais aos cards.
"""
import hashlib
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base


class DeckAudio(Base):
    __tablename__ = "deck_audio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # unique: um roteiro por deck. Regerar SUBSTITUI, não acumula --
    # manter histórico de roteiros não serve a ninguém e só faria a
    # tabela crescer sem leitor.
    deck_id: Mapped[int] = mapped_column(
        ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # [{"titulo": str, "falas": [{"quem": str, "texto": str}]}]
    roteiro: Mapped[list] = mapped_column(JSON, nullable=False)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def calcular_hash_do_deck(pares: list[tuple[str, str]]) -> str:
    """Retrato do conteúdo de um deck: SHA-256 de todos os cards.

    Ordenado de propósito -- reordenar os cards não muda o que o áudio
    precisa dizer, então não deve marcar o roteiro como atrasado. O que
    marca é texto entrando, saindo ou mudando.
    """
    corpo = "\n".join(sorted(f"{frente}\x1f{verso}" for frente, verso in pares))
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()
