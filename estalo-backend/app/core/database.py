"""
Conexão com o banco de dados.

Aqui a gente cria:
- engine: o "encanamento" que conversa com o banco
- SessionLocal: cada requisição abre uma sessão (uma conversa) e fecha no fim
- Base: a classe-mãe que todos os modelos herdam
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# O connect_args só é necessário pro SQLite. Em PostgreSQL ele é ignorado.
connect_args = (
    {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependência do FastAPI: abre uma sessão por requisição e fecha no fim."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
