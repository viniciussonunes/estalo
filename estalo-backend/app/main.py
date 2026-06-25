from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.database import Base, engine
from app import models  # noqa: F401
from app.routers import auth, folders, decks, cards, study

Base.metadata.create_all(bind=engine)


def _migrar():
    """Adiciona colunas novas em tabelas existentes (sem Alembic)."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        colunas_cards = {c["name"] for c in inspector.get_columns("cards")}
        if "options" not in colunas_cards:
            conn.execute(text("ALTER TABLE cards ADD COLUMN options TEXT"))
        if "explanation" not in colunas_cards:
            conn.execute(text("ALTER TABLE cards ADD COLUMN explanation TEXT"))


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
