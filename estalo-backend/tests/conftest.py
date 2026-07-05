"""
Fixtures compartilhadas da suíte pytest (tests/).

Isso é uma camada NOVA e PARALELA à suíte antiga (os scripts test_*.py na
raiz do projeto, print+assert, que rodam contra o estalo.db local de
verdade) — não substitui aquilo, migrar os scripts antigos pra cá não foi
pedido. São filosofias diferentes: os scripts antigos validam contra o
banco real de dev (inclusive contra o Gemini real, quando testam IA);
esta suíte roda inteira em memória, isolada, rápida o bastante pra virar
gate de pre-commit (ver smoke_tests.py).

IMPORTANTE sobre ordem de import: TESTING=true precisa estar setado ANTES
de qualquer "from app..." acontecer neste processo — app/core/database.py
lê essa variável na hora de montar o engine, uma única vez. Setar a env
var aqui, no topo do conftest.py, garante isso: pytest sempre importa
conftest.py antes de qualquer teste.
"""
import os

os.environ["TESTING"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, engine, get_db
from app.main import app
from tests.factories import ALL_FACTORIES


@pytest.fixture()
def db_session():
    """Schema novo, vazio, só pra este teste — destruído (drop_all) no
    final. StaticPool (ver database.py) garante que create_all/drop_all
    aqui enxergam a MESMA conexão em memória usada pelo resto do teste."""
    Base.metadata.create_all(bind=engine)
    connection = engine.connect()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        connection.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    """TestClient com get_db() sobrescrito pra usar a MESMA sessão de
    db_session — assim o teste consegue inspecionar direto o que o
    endpoint gravou (mesma conexão, mesma visão dos dados)."""
    def _sessao_de_teste():
        yield db_session

    app.dependency_overrides[get_db] = _sessao_de_teste
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def bind_factories(db_session):
    """Liga as factories (tests/factories.py) na sessão deste teste —
    autouse, então todo teste em tests/ já ganha isso de graça. Fica aqui
    (não em factories.py) porque só conftest.py é garantido de ser
    importado por pytest antes da coleta dos testes."""
    for f in ALL_FACTORIES:
        f._meta.sqlalchemy_session = db_session
        f._meta.sqlalchemy_session_persistence = "commit"
    yield
