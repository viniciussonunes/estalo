"""
Checklist crítico — pensado pra rodar em segundos (banco em memória, IA
mockada) antes de qualquer commit:

    pytest tests/smoke_tests.py -v

Cada teste aqui é deliberadamente RASO: só confirma que o caminho básico
de cada funcionalidade central não quebrou. Profundidade de regra de
negócio (SM-2 exato, timezone, dedup por content_hash, etc.) já é coberta
pelos testes específicos — tanto os scripts na raiz do projeto quanto o
resto de tests/. Isso aqui é o "será que alguma coisa óbvia quebrou",
não "está tudo certo em detalhe".

IMPORTANTE: smoke_tests.py (nome no plural, sem prefixo test_) só é
descoberto pelo pytest por causa do `python_files` customizado em
pytest.ini — sem isso, o pytest ignoraria este arquivo silenciosamente.
"""
import json
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.config import settings

FIXTURES = Path(__file__).parent / "fixtures"


def _apkg_minimo(caminho: Path) -> None:
    sqlite_path = caminho.parent / "smoke.sqlite"
    conn = sqlite3.connect(sqlite_path)
    conn.executescript("""
        CREATE TABLE col (id INTEGER PRIMARY KEY, crt INTEGER, mod INTEGER, scm INTEGER,
            ver INTEGER, dty INTEGER, usn INTEGER, ls INTEGER, conf TEXT, models TEXT,
            decks TEXT, dconf TEXT, tags TEXT);
        CREATE TABLE notes (id INTEGER PRIMARY KEY, guid TEXT, mid INTEGER, mod INTEGER,
            usn INTEGER, tags TEXT, flds TEXT, sfld TEXT, csum INTEGER, flags INTEGER, data TEXT);
        CREATE TABLE cards (id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER, ord INTEGER,
            mod INTEGER, usn INTEGER, type INTEGER, queue INTEGER, due INTEGER, ivl INTEGER,
            factor INTEGER, reps INTEGER, lapses INTEGER, left INTEGER, odue INTEGER,
            odid INTEGER, flags INTEGER, data TEXT);
    """)
    modelos = {"1": {"type": 0, "tmpls": [{"name": "Card 1"}]}}
    conn.execute("INSERT INTO col VALUES (1,0,0,0,11,0,0,0,'{}',?,'{}','{}','')", (json.dumps(modelos),))
    conn.execute("INSERT INTO notes VALUES (1, 'g1', 1, 0, 0, '', 'Smoke front\x1fSmoke back', 'Smoke front', 0, 0, '')")
    conn.execute("INSERT INTO cards VALUES (1, 1, 1, 0, 0, 0, 2, 2, 10, 15, 2500, 4, 0, 0, 0, 0, 0, '')")
    conn.commit()
    conn.close()
    with zipfile.ZipFile(caminho, "w") as z:
        z.write(sqlite_path, arcname="collection.anki2")


def _registrar_e_logar(client, email="smoke@estalo.dev"):
    client.post("/auth/register", json={"email": email, "password": "senha123"})
    login = client.post("/auth/login", data={"username": email, "password": "senha123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_criar_conta_e_logar(client):
    auth = _registrar_e_logar(client)
    me = client.get("/auth/me", headers=auth)
    assert me.status_code == 200
    assert me.json()["email"] == "smoke@estalo.dev"


def test_criar_pasta(client):
    auth = _registrar_e_logar(client, "smoke_pasta@estalo.dev")
    r = client.post("/folders", json={"name": "Pasta Smoke"}, headers=auth)
    assert r.status_code == 201


def test_criar_deck(client):
    auth = _registrar_e_logar(client, "smoke_deck@estalo.dev")
    r = client.post("/decks", json={"title": "Deck Smoke"}, headers=auth)
    assert r.status_code == 201
    assert r.json()["title"] == "Deck Smoke"


def test_criar_card_manual(client):
    auth = _registrar_e_logar(client, "smoke_card@estalo.dev")
    deck = client.post("/decks", json={"title": "Deck Smoke Card"}, headers=auth).json()
    r = client.post(f"/decks/{deck['id']}/cards", json={"front": "F", "back": "B"}, headers=auth)
    assert r.status_code == 201
    assert r.json()["front"] == "F"


def test_estudar_e_responder_card(client):
    auth = _registrar_e_logar(client, "smoke_estudo@estalo.dev")
    deck = client.post("/decks", json={"title": "Deck Smoke Estudo"}, headers=auth).json()
    client.post(f"/decks/{deck['id']}/cards", json={"front": "F", "back": "B"}, headers=auth)
    prox = client.get(f"/study/decks/{deck['id']}/next", headers=auth).json()
    r = client.post(f"/study/cards/{prox['card_id']}/answer", json={"quality": 4}, headers=auth)
    assert r.status_code == 200
    assert r.json()["repetitions"] == 1


def test_gerar_card_com_ia_mockada(client):
    """IA mockada de propósito (ver tests/test_ai_mocked.py) -- smoke test
    tem que ser rápido e não depender de rede/GEMINI_API_KEY real."""
    auth = _registrar_e_logar(client, "smoke_ia@estalo.dev")
    deck = client.post("/decks", json={"title": "Deck Smoke IA"}, headers=auth).json()

    corpo = json.loads((FIXTURES / "gemini_response_success.json").read_text())
    resp_mock = Mock()
    resp_mock.status_code = 200
    resp_mock.json.return_value = corpo
    resp_mock.raise_for_status.return_value = None

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=resp_mock):
        r = client.post(
            f"/decks/{deck['id']}/cards/generate",
            json={"text": "Capitais da Europa, texto de exemplo suficientemente longo.", "quantity": 2},
            headers=auth,
        )
    assert r.status_code == 201
    assert len(r.json()) == 2


def test_importar_anki(client, tmp_path):
    auth = _registrar_e_logar(client, "smoke_import@estalo.dev")
    deck = client.post("/decks", json={"title": "Deck Smoke Import"}, headers=auth).json()

    apkg = tmp_path / "smoke.apkg"
    _apkg_minimo(apkg)

    with open(apkg, "rb") as f:
        r = client.post(
            "/import/anki",
            data={"deck_id": deck["id"]},
            files={"arquivo": ("smoke.apkg", f, "application/octet-stream")},
            headers=auth,
        )
    assert r.status_code == 201
    job_id = r.json()["job_id"]

    r2 = client.post(f"/import/anki/{job_id}/process-batch", headers=auth)
    assert r2.status_code == 200
    assert r2.json() == {"processed": 1, "total": 1, "errors": 0}

    cards = client.get(f"/decks/{deck['id']}/cards", headers=auth).json()
    assert any(c["back"] == "Smoke back" for c in cards)


def test_excluir_deck_em_cascata(client):
    auth = _registrar_e_logar(client, "smoke_delete@estalo.dev")
    deck = client.post("/decks", json={"title": "Deck Smoke Delete"}, headers=auth).json()
    card = client.post(f"/decks/{deck['id']}/cards", json={"front": "F", "back": "B"}, headers=auth).json()

    r = client.delete(f"/decks/{deck['id']}", headers=auth)
    assert r.status_code == 204

    r2 = client.get(f"/cards/{card['id']}", headers=auth)
    assert r2.status_code == 404
