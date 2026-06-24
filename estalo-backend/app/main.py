"""
Ponto de entrada da API.

Cria as tabelas no banco, expõe o endpoint de saúde e liga os routers
(autenticação, pastas, decks, cards e estudo).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import Base, engine
from app import models  # noqa: F401 — garante que os modelos sejam registrados
from app.routers import auth, folders, decks, cards, study

# Cria as tabelas se ainda não existirem.
# (No futuro a gente troca isso por Alembic, que controla versões do banco.)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Estalo API", version="0.7.0")

# CORS: libera o frontend (que roda noutra porta) a falar com a API.
# O Vite sobe em localhost:5173 por padrão. Em produção, troque pela URL real do site.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Liga os endpoints.
app.include_router(auth.router)
app.include_router(folders.router)
app.include_router(decks.router)
app.include_router(cards.router)
app.include_router(study.router)


@app.get("/")
def health():
    return {"status": "ok", "app": "Estalo", "version": "0.7.0"}
