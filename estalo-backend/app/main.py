import os

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.database import Base, engine
from app import models  # noqa: F401
from app.models.card import calcular_content_hash
from app.routers import admin, auth, folders, decks, cards, study, import_anki, challenges

# Precisa vir ANTES de tudo (inclusive de _migrar()/create_all() logo
# abaixo) -- assim uma falha na migração no cold start também é capturada,
# não só exceções dentro de requests. Diferente do SDK JS (frontend, ver
# src/sentry.js), o SDK Python não tem uma opção `enabled` -- ele já vira
# no-op sozinho com dsn="" (nada é validado/enviado), então é seguro
# chamar init() incondicionalmente mesmo sem conta no Sentry (dev/CI).
#
# environment usa VERCEL_ENV (injetada automaticamente pela própria
# Vercel: "production" | "preview" | "development") -- não precisa de
# variável própria pra isso, e não existe localmente (cai pro default).
#
# send_default_pii=False é explícito de propósito: não queremos que o SDK
# infira e envie dados de usuário (email, IP) sozinho pros eventos.
sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    environment=os.getenv("VERCEL_ENV", "development"),
    integrations=[StarletteIntegration(), FastApiIntegration()],
    traces_sample_rate=0.1,
    send_default_pii=False,
)


def _migrar():
    """Adiciona colunas/índices novos em tabelas existentes (sem Alembic).

    Base.metadata.create_all() só cria tabelas que ainda não existem — em
    bancos já populados (Neon em produção, ou o SQLite local de quem já
    rodou o projeto antes), as tabelas já estão lá e create_all() não mexe
    nelas. Por isso os índices também entram aqui, não só nos models.

    Tudo dentro do MESMO `with engine.begin() as conn:` — é o que garante a
    atomicidade: se qualquer passo (ALTER, backfill, CREATE INDEX) falhar,
    a transação inteira volta atrás, incluindo os passos anteriores desta
    mesma chamada. SQLite e Postgres suportam DDL transacional, então isso
    vale tanto pra ALTER TABLE/CREATE TABLE quanto pros UPDATEs do backfill.
    """
    with engine.begin() as conn:
        # inspect(conn) -- NÃO inspect(engine) -- de propósito: ligado à
        # MESMA conexão que já está em transação aberta (ver comentário
        # sobre BEGIN IMMEDIATE em database.py). inspect(engine) faria
        # Inspector.get_columns() pedir uma conexão PRÓPRIA do pool — com
        # BEGIN IMMEDIATE, essa segunda conexão trava esperando a primeira
        # (que está parada esperando ELA terminar), autodeadlock. Achado
        # testando o fix do busy_timeout/BEGIN IMMEDIATE contra concorrência
        # real.
        inspector = inspect(conn)
        colunas_cards = {c["name"] for c in inspector.get_columns("cards")}
        if "options" not in colunas_cards:
            conn.execute(text("ALTER TABLE cards ADD COLUMN options TEXT"))
        if "explanation" not in colunas_cards:
            conn.execute(text("ALTER TABLE cards ADD COLUMN explanation TEXT"))
        if "content_hash" not in colunas_cards:
            conn.execute(text("ALTER TABLE cards ADD COLUMN content_hash VARCHAR(64)"))
        if "tutor_explanation" not in colunas_cards:
            conn.execute(text("ALTER TABLE cards ADD COLUMN tutor_explanation TEXT"))

        colunas_pastas = {c["name"] for c in inspector.get_columns("folders")}
        if "color" not in colunas_pastas:
            conn.execute(text("ALTER TABLE folders ADD COLUMN color TEXT"))

        # Backfill do content_hash pra cards que ainda não têm — SHA-256
        # não é nativo nem em SQLite nem em Postgres sem extensão, então
        # roda em Python (calcular_content_hash), não em SQL puro.
        linhas = conn.execute(
            text("SELECT id, front, back FROM cards WHERE content_hash IS NULL")
        ).fetchall()
        for linha in linhas:
            conn.execute(
                text("UPDATE cards SET content_hash = :hash WHERE id = :id"),
                {"hash": calcular_content_hash(linha.front, linha.back), "id": linha.id},
            )

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
        # Não-único de propósito — ver comentário em models/card.py sobre
        # por que duplicata é definida por deck, não por uma constraint
        # global (evita quebrar a migração se já existir duplicata hoje, e
        # evita vazar entre usuários/decks diferentes).
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_cards_deck_content_hash "
            "ON cards (deck_id, content_hash)"
        ))


# create_all()/_migrar() fazem várias idas ao banco (checar tabelas, colunas
# e índices existentes) — na Vercel isso corria em TODO cold start, não só
# na primeira vez, e cada cold start pagava essa latência antes de responder
# a primeira request.
#
# Em dev local (a Vercel injeta a env var VERCEL=1 em produção; localmente
# ela não existe) continua rodando sempre, sem fricção — é rápido no SQLite
# e garante que o banco local sempre existe/está atualizado.
#
# Em produção só roda se RUN_MIGRATIONS=1 estiver setado explicitamente:
# depois de mudar o schema (nova coluna, novo índice), seta essa variável
# na Vercel e faz um deploy pra aplicar. create_all()/_migrar() são
# idempotentes (IF NOT EXISTS em tudo), então não tem risco em deixar
# setada por engano — só o custo de latência que este guard evita no dia a
# dia.
if os.getenv("RUN_MIGRATIONS") == "1" or not os.getenv("VERCEL"):
    Base.metadata.create_all(bind=engine)
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
app.include_router(import_anki.router)
app.include_router(admin.router)
app.include_router(challenges.router)


@app.get("/")
def health():
    return {"status": "ok", "app": "Estalo", "version": "0.8.0"}
