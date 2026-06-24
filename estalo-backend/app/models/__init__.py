"""
Junta todos os modelos num lugar só, pra o SQLAlchemy enxergar todos
quando for criar as tabelas.
"""
from app.models.card import Card
from app.models.deck import Deck
from app.models.folder import Folder
from app.models.review import Review
from app.models.user import User

__all__ = ["User", "Folder", "Deck", "Card", "Review"]
