"""
Junta todos os modelos num lugar só, pra o SQLAlchemy enxergar todos
quando for criar as tabelas.
"""
from app.models.card import Card
from app.models.challenge import Challenge
from app.models.deck import Deck
from app.models.explanation_cache import ExplanationCache
from app.models.explanation_log import ExplanationLog
from app.models.folder import Folder
from app.models.import_staging import ImportStagingCard
from app.models.review import Review
from app.models.review_history import ReviewHistory
from app.models.study_session import StudySession
from app.models.user import User
from app.models.user_quota import UserQuota

__all__ = [
    "User", "Folder", "Deck", "Card", "Review", "ReviewHistory",
    "StudySession", "ImportStagingCard", "UserQuota",
    "ExplanationCache", "ExplanationLog", "Challenge",
]
