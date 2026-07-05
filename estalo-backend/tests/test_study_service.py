"""
Teste do "Estudo por Pasta" — get_all_deck_ids_in_folder() (unitário) e
GET /study/global-reviews?folder_id=... (integração via HTTP real).

Hierarquia usada em quase todos os testes:

    Pasta A (raiz)
      └── Pasta A1
            └── Pasta A1a
    Pasta B (raiz, sem relação com A)

    Deck em A (direto), deck em A1, deck em A1a, deck em B, deck solto
    (sem pasta nenhuma) — cada um com 1 card + 1 Review já vencido.
"""
from datetime import datetime, timedelta

from app.models import User
from app.services.study_service import get_all_deck_ids_in_folder
from tests.factories import CardFactory, DeckFactory, FolderFactory, ReviewFactory, UserFactory


def _registrar_e_logar(client, db_session, email="study_service@estalo.dev"):
    client.post("/auth/register", json={"email": email, "password": "senha123"})
    login = client.post("/auth/login", data={"username": email, "password": "senha123"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    user = db_session.query(User).filter(User.email == email).first()
    return auth, user


def _deck_com_card_vencido(db_session, user, folder=None):
    deck = DeckFactory(owner=user, folder=folder)
    card = CardFactory(deck=deck)
    ReviewFactory(user=user, card=card, due_date=datetime.utcnow() - timedelta(days=1))
    db_session.commit()
    return deck


# --- Testes unitários de get_all_deck_ids_in_folder ------------------------

def test_get_all_deck_ids_in_folder_recursivo(db_session):
    user = UserFactory()
    db_session.commit()

    pasta_a = FolderFactory(owner=user, name="A")
    pasta_a1 = FolderFactory(owner=user, name="A1", parent=pasta_a, depth=2)
    pasta_a1a = FolderFactory(owner=user, name="A1a", parent=pasta_a1, depth=3)
    pasta_b = FolderFactory(owner=user, name="B")
    db_session.commit()

    deck_a = DeckFactory(owner=user, folder=pasta_a)
    deck_a1 = DeckFactory(owner=user, folder=pasta_a1)
    deck_a1a = DeckFactory(owner=user, folder=pasta_a1a)
    deck_b = DeckFactory(owner=user, folder=pasta_b)
    db_session.commit()

    ids = get_all_deck_ids_in_folder(pasta_a.id, user.id, db_session)

    assert set(ids) == {deck_a.id, deck_a1.id, deck_a1a.id}
    assert deck_b.id not in ids


def test_get_all_deck_ids_in_folder_pasta_vazia_retorna_lista_vazia(db_session):
    user = UserFactory()
    db_session.commit()
    pasta_vazia = FolderFactory(owner=user, name="Vazia")
    db_session.commit()

    ids = get_all_deck_ids_in_folder(pasta_vazia.id, user.id, db_session)

    assert ids == []


def test_get_all_deck_ids_in_folder_nao_vaza_dados_de_outro_usuario(db_session):
    dono = UserFactory()
    intruso = UserFactory()
    db_session.commit()

    pasta_do_dono = FolderFactory(owner=dono, name="Privada")
    db_session.commit()
    DeckFactory(owner=dono, folder=pasta_do_dono)
    db_session.commit()

    # Pede a MESMA pasta, mas se autenticando como o intruso.
    ids = get_all_deck_ids_in_folder(pasta_do_dono.id, intruso.id, db_session)

    assert ids == []


# --- Testes de integração via HTTP (GET /study/global-reviews?folder_id=) --

def test_endpoint_modo_global_conta_todos_os_decks(client, db_session):
    auth, user = _registrar_e_logar(client, db_session)

    pasta_a = FolderFactory(owner=user, name="A")
    db_session.commit()
    _deck_com_card_vencido(db_session, user, folder=pasta_a)
    _deck_com_card_vencido(db_session, user, folder=None)  # deck solto, sem pasta
    _deck_com_card_vencido(db_session, user, folder=None)

    r = client.get("/study/global-reviews", headers=auth)
    assert r.status_code == 200
    assert len(r.json()) == 3  # os 3 decks têm 1 card vencido cada


def test_endpoint_folder_id_filtra_pasta_e_subpastas(client, db_session):
    auth, user = _registrar_e_logar(client, db_session, "study_service_folder@estalo.dev")

    pasta_a = FolderFactory(owner=user, name="A")
    pasta_a1 = FolderFactory(owner=user, name="A1", parent=pasta_a, depth=2)
    pasta_b = FolderFactory(owner=user, name="B")
    db_session.commit()

    _deck_com_card_vencido(db_session, user, folder=pasta_a)
    _deck_com_card_vencido(db_session, user, folder=pasta_a1)
    _deck_com_card_vencido(db_session, user, folder=pasta_b)  # não deve entrar
    _deck_com_card_vencido(db_session, user, folder=None)      # não deve entrar

    r = client.get(f"/study/global-reviews?folder_id={pasta_a.id}", headers=auth)
    assert r.status_code == 200
    assert len(r.json()) == 2  # só os decks de A + A1


def test_endpoint_pasta_vazia_retorna_lista_vazia_sem_erro(client, db_session):
    auth, user = _registrar_e_logar(client, db_session, "study_service_empty@estalo.dev")
    pasta_vazia = FolderFactory(owner=user, name="Vazia")
    db_session.commit()

    r = client.get(f"/study/global-reviews?folder_id={pasta_vazia.id}", headers=auth)
    assert r.status_code == 200
    assert r.json() == []


def test_endpoint_folder_id_de_outro_usuario_ou_inexistente_da_404(client, db_session):
    auth, _user = _registrar_e_logar(client, db_session, "study_service_404@estalo.dev")

    r = client.get("/study/global-reviews?folder_id=999999", headers=auth)
    assert r.status_code == 404
