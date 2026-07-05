"""
Conexão com o banco de dados.

Aqui a gente cria:
- engine: o "encanamento" que conversa com o banco
- SessionLocal: cada requisição abre uma sessão (uma conversa) e fecha no fim
- Base: a classe-mãe que todos os modelos herdam
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# DATABASE_URL_POOL (endpoint "-pooler" do Neon, via PgBouncer) tem prioridade
# se estiver setada; senão cai pra DATABASE_URL de sempre — sem mudar nada
# pra quem não configurar a variável nova. Nota: _migrar() (main.py) usa esse
# mesmo engine, então migrações também passam pelo pooler quando ativo; o
# PgBouncer do Neon em modo transaction lida bem com o DDL simples usado lá
# (ALTER TABLE, CREATE INDEX IF NOT EXISTS).
DATABASE_URL = settings.DATABASE_URL_POOL or settings.DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")

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

engine = create_engine(DATABASE_URL, connect_args=connect_args, **_pool_kwargs)

if _is_sqlite:
    # Sem isso, o driver stdlib `sqlite3` do Python comita implicitamente
    # ANTES de rodar qualquer DDL (ALTER TABLE, CREATE TABLE, CREATE INDEX)
    # mesmo dentro de uma transação SQLAlchemy aberta com `engine.begin()`.
    # Descoberto testando o rollback de _migrar() (main.py): um ALTER TABLE
    # ficava commitado mesmo quando um passo POSTERIOR da mesma migração
    # falhava — o SQLite em si suporta DDL transacional de verdade, o
    # comportamento legado é só do driver Python. Esta é a correção que o
    # próprio SQLAlchemy recomenda: desligar o autocommit implícito do
    # driver e deixar o SQLAlchemy emitir BEGIN/COMMIT explicitamente.
    # Postgres (produção) não precisa disso — DDL transacional já é padrão.
    @event.listens_for(engine, "connect")
    def _sqlite_sem_autocommit_implicito(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _sqlite_begin_explicito(conn):
        conn.exec_driver_sql("BEGIN")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependência do FastAPI: abre uma sessão por requisição e fecha no fim."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
