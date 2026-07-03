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

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# O connect_args só é necessário pro SQLite. Em PostgreSQL ele é ignorado.
connect_args = {"check_same_thread": False} if _is_sqlite else {}

# Sem esse tuning, o QueuePool padrão do SQLAlchemy abre até 15 conexões
# (5 + 10 de overflow) POR INSTÂNCIA — e na Vercel serverless cada cold
# start recria o engine do zero. Sob carga, várias instâncias simultâneas
# multiplicam isso rápido contra o limite de conexões do Neon. Um pool
# pequeno é o certo aqui: cada instância vive pouco tempo e atende poucas
# requisições, então não precisa (nem deve) seguar muitas conexões presas.
# pool_pre_ping evita usar uma conexão que o Neon já fechou por trás
# (comum depois de idle); pool_recycle descarta conexões antigas antes
# que isso aconteça.
_pool_kwargs = {} if _is_sqlite else {
    "pool_size": 3,
    "max_overflow": 2,
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, **_pool_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependência do FastAPI: abre uma sessão por requisição e fecha no fim."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
