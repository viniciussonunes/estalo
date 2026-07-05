"""Checagem rápida da infraestrutura nova (banco em memória + factories)
antes de escrever os testes de verdade -- se isso quebrar, tudo mais quebra."""
from tests.factories import CardFactory, DeckFactory, UserFactory


def test_db_session_isolado_e_funcional(db_session):
    from app.models import User
    assert db_session.query(User).count() == 0
    db_session.add(User(email="x@x.com", hashed_password="y"))
    db_session.commit()
    assert db_session.query(User).count() == 1


def test_factories_criam_e_persistem(db_session):
    deck = DeckFactory()
    card1 = CardFactory(deck=deck)
    card2 = CardFactory(deck=deck)
    db_session.commit()
    assert db_session.query(type(deck)).count() == 1
    assert card1.deck_id == deck.id == card2.deck_id
    assert card1.content_hash is not None
    assert card1.content_hash != card2.content_hash  # fronts/backs aleatórios do Faker


def test_client_e_db_session_veem_o_mesmo_banco(client, db_session):
    from app.models import Deck
    r = client.post("/auth/register", json={"email": "sanity@estalo.dev", "password": "senha123"})
    assert r.status_code == 201
    login = client.post("/auth/login", data={"username": "sanity@estalo.dev", "password": "senha123"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.post("/decks", json={"title": "Deck Sanity"}, headers=auth)
    assert db_session.query(Deck).filter(Deck.title == "Deck Sanity").count() == 1
