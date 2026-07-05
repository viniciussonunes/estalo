"""
Conexão com o banco de dados.

Aqui a gente cria:
- engine: o "encanamento" que conversa com o banco
- SessionLocal: cada requisição abre uma sessão (uma conversa) e fecha no fim
- Base: a classe-mãe que todos os modelos herdam
"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

# TESTING=true força SQLite em memória, isolado por processo — usado pela
# suíte pytest em tests/ (ver tests/conftest.py), nunca em dev/produção.
# Precisa ser setado ANTES deste módulo ser importado pela primeira vez
# (engine é construído uma única vez, no import).
TESTING = os.getenv("TESTING", "").lower() == "true"

if TESTING:
    DATABASE_URL = "sqlite:///:memory:"
    _is_sqlite = True
    connect_args = {"check_same_thread": False}
    # StaticPool é obrigatório aqui: sem ele, cada conexão nova do pool
    # abriria um :memory: DIFERENTE (SQLite cria um banco em memória por
    # conexão, não um banco compartilhado) — a segunda query do teste
    # veria um banco vazio. StaticPool faz o engine reusar SEMPRE a mesma
    # única conexão.
    _pool_kwargs = {"poolclass": StaticPool}
else:
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
    def _sqlite_configurar_conexao(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

        # SQLite só permite UM escritor por vez, e por padrão não espera
        # nada: a segunda transação que tenta escrever enquanto outra
        # ainda está aberta falha na hora com "database is locked" — visto
        # na prática quando _salvarProgresso() (Aprender.jsx) dispara
        # várias respostas em paralelo via Promise.all, cada uma abrindo
        # sua própria transação de escrita. busy_timeout faz o SQLite
        # tentar de novo por até 5s antes de desistir, em vez de falhar na
        # primeira colisão — cobre bem concorrência de vida curta como
        # essa. Não é um substituto pra locking de linha de verdade
        # (Postgres, em produção, já tem isso e não sofre desse problema).
        dbapi_connection.execute("PRAGMA busy_timeout = 5000")

    @event.listens_for(engine, "begin")
    def _sqlite_begin_explicito(conn):
        # Com StaticPool (usado em TESTING=true — ver acima), a MESMA
        # conexão física é compartilhada por tudo, inclusive por
        # ferramentas internas do SQLAlchemy (ex: Inspector.get_columns(),
        # usado em main.py:_migrar()) que pedem uma conexão "nova" do pool
        # no meio de uma transação já aberta — StaticPool devolve essa
        # MESMA conexão, e sem essa checagem o "BEGIN" duplicado quebra
        # com "cannot start a transaction within a transaction". Com pool
        # normal (dev/produção) isso nunca colide, porque cada checkout
        # tende a ser uma conexão diferente — mas checar in_transaction
        # antes de sempre emitir o BEGIN é seguro e correto nos dois casos.
        if not conn.connection.dbapi_connection.in_transaction:
            # IMMEDIATE, não o "BEGIN" (deferred) puro: testando o
            # busy_timeout acima, descobri que ele sozinho NÃO bastava sob
            # concorrência real (Promise.all de 5-6 respostas simultâneas
            # ainda derrubava algumas com "database is locked"). O motivo:
            # BEGIN deferred não pega lock nenhum até o primeiro
            # SELECT/UPDATE — várias transações concorrentes conseguem
            # todas pegar o lock de LEITURA compartilhado, e quando cada
            # uma tenta promover pra escrita ao mesmo tempo, ninguém cede
            # (impasse circular que o retry do busy_timeout não desfaz
            # sozinho). IMMEDIATE pega a intenção de escrita JÁ na largada
            # — serializa quem quer escrever, sem bloquear quem só lê — e
            # combinado com o busy_timeout, isso sim garante que todo mundo
            # espera a vez em vez de falhar. Confirmado com teste de carga
            # (múltiplas respostas HTTP concorrentes de verdade).
            conn.exec_driver_sql("BEGIN IMMEDIATE")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependência do FastAPI: abre uma sessão por requisição e fecha no fim."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
