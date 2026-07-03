from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.database import Base, engine
from app import models  # noqa: F401
from app.routers import auth, folders, decks, cards, study

Base.metadata.create_all(bind=engine)


def _migrar():
    """Adiciona colunas/índices novos em tabelas existentes (sem Alembic).

    Base.metadata.create_all() só cria tabelas que ainda não existem — em
    bancos já populados (Neon em produção, ou o SQLite local de quem já
    rodou o projeto antes), as tabelas já estão lá e create_all() não mexe
    nelas. Por isso os índices também entram aqui, não só nos models.
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        colunas_cards = {c["name"] for c in inspector.get_columns("cards")}
        if "options" not in colunas_cards:
            conn.execute(text("ALTER TABLE cards ADD COLUMN options TEXT"))
        if "explanation" not in colunas_cards:
            conn.execute(text("ALTER TABLE cards ADD COLUMN explanation TEXT"))

        # Índices — nomes iguais aos que o SQLAlchemy geraria sozinho num
        # banco novo (ix_<tabela>_<coluna>), pra ficar consistente entre
        # create_all() (banco novo) e essa migração manual (banco existente).
        # IF NOT EXISTS funciona em Postgres e em SQLite (>=3.8), então é
        # seguro rodar em toda inicialização.
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_cards_deck_id ON cards (deck_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_decks_owner_id ON decks (owner_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_review_history_user_avaliado "
            "ON review_history (user_id, avaliado_em)"
        ))


_migrar()

app = FastAPI(title="Estalo API", version="0.8.0")

# CORS dinâmico: sempre permite localhost em dev; adiciona a URL da Vercel em prod.
_origens = ["http://localhost:5173", "http://localhost:3000"]
if settings.FRONTEND_URL:
    _origens.append(settings.FRONTEND_URL.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origens,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(folders.router)
app.include_router(decks.router)
app.include_router(cards.router)
app.include_router(study.router)


@app.get("/")
def health():
    return {"status": "ok", "app": "Estalo", "version": "0.8.0"}
