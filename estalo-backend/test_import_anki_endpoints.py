"""Teste E2E dos endpoints do Motor de Importação Anki (via HTTP de verdade,
TestClient + upload multipart real -- não chama o orquestrador direto)."""
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
SCRATCH = Path(tempfile.mkdtemp(prefix="estalo_test_import_endpoints_"))


def logar(email, senha="senha123"):
    client.post("/auth/register", json={"email": email, "password": senha})
    r = client.post("/auth/login", data={"username": email, "password": senha})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _construir_apkg(caminho_apkg: Path, pares: list[tuple[str, str]]) -> None:
    caminho_sqlite = caminho_apkg.parent / f"{caminho_apkg.stem}.sqlite"
    if caminho_sqlite.exists():
        caminho_sqlite.unlink()
    conn = sqlite3.connect(caminho_sqlite)
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
    for i, (front, back) in enumerate(pares, start=1):
        conn.execute("INSERT INTO notes VALUES (?, ?, 1, 0, 0, '', ?, ?, 0, 0, '')",
                      (i, f"guid{i}", f"{front}\x1f{back}", front))
        conn.execute("INSERT INTO cards VALUES (?, ?, 1, 0, 0, 0, 2, 2, 10, 15, 2500, 4, 0, 0, 0, 0, 0, '')", (i, i))
    conn.commit()
    conn.close()
    with zipfile.ZipFile(caminho_apkg, "w") as z:
        z.write(caminho_sqlite, arcname="collection.anki2")
    caminho_sqlite.unlink()


vini = logar("import_ep_vini@estalo.dev")
outro = logar("import_ep_outro@estalo.dev")

deck_vini = client.post("/decks", json={"title": "Deck Endpoint Vini"}, headers=vini).json()
deck_outro = client.post("/decks", json={"title": "Deck Endpoint Outro"}, headers=outro).json()

pares = [("Capital da França?", "Paris"), ("Capital da Itália?", "Roma"), ("Capital do Japão?", "Tóquio")]
apkg_valido = SCRATCH / "valido.apkg"
_construir_apkg(apkg_valido, pares)

print("1) POST /import/anki com deck de outro usuário -> 404...")
with open(apkg_valido, "rb") as f:
    r = client.post(
        "/import/anki",
        data={"deck_id": deck_outro["id"]},
        files={"arquivo": ("deck.apkg", f, "application/octet-stream")},
        headers=vini,
    )
assert r.status_code == 404, r.text
print(f"   OK -- {r.status_code} {r.json()}\n")

print("2) POST /import/anki com extensão errada -> 400...")
txt = SCRATCH / "nao_e_apkg.txt"
txt.write_text("isso não é um apkg")
with open(txt, "rb") as f:
    r = client.post(
        "/import/anki",
        data={"deck_id": deck_vini["id"]},
        files={"arquivo": ("nao_e_apkg.txt", f, "text/plain")},
        headers=vini,
    )
assert r.status_code == 400, r.text
print(f"   OK -- {r.status_code} {r.json()}\n")

print("3) POST /import/anki com .apkg corrompido -> 400, sem gravar staging...")
corrompido = SCRATCH / "corrompido.apkg"
corrompido.write_bytes(b"lixo binario")
with open(corrompido, "rb") as f:
    r = client.post(
        "/import/anki",
        data={"deck_id": deck_vini["id"]},
        files={"arquivo": ("corrompido.apkg", f, "application/octet-stream")},
        headers=vini,
    )
assert r.status_code == 400, r.text
print(f"   OK -- {r.status_code} {r.json()}\n")

print("4) POST /import/anki válido -> 201 + job_id...")
with open(apkg_valido, "rb") as f:
    r = client.post(
        "/import/anki",
        data={"deck_id": deck_vini["id"]},
        files={"arquivo": ("valido.apkg", f, "application/octet-stream")},
        headers=vini,
    )
assert r.status_code == 201, r.text
job_id = r.json()["job_id"]
assert isinstance(job_id, str) and len(job_id) > 0
print(f"   OK -- job_id={job_id}\n")

print("5) process-batch com token de OUTRO usuário -> 404 (não vaza o job)...")
r = client.post(f"/import/anki/{job_id}/process-batch", headers=outro)
assert r.status_code == 404, r.text
print(f"   OK -- {r.status_code}\n")

print("6) process-batch com job_id inexistente -> 404...")
r = client.post("/import/anki/job-que-nao-existe/process-batch", headers=vini)
assert r.status_code == 404, r.text
print(f"   OK -- {r.status_code}\n")

print("7) process-batch do dono -> 200, progresso correto, mesmo sem erros...")
r = client.post(f"/import/anki/{job_id}/process-batch?batch_size=200", headers=vini)
assert r.status_code == 200, r.text
progresso = r.json()
print("   progresso:", progresso)
assert progresso == {"processed": 3, "total": 3, "errors": 0}
print("   OK\n")

print("8) Cards de verdade aparecem no deck depois do process-batch...")
cards = client.get(f"/decks/{deck_vini['id']}/cards", headers=vini).json()
backs = {c["back"] for c in cards}
assert {"Paris", "Roma", "Tóquio"} <= backs
print(f"   OK -- {len(cards)} cards no deck\n")

print("9) Chamar process-batch de novo num job já 100% processado -> continua 200, nada quebra...")
r = client.post(f"/import/anki/{job_id}/process-batch", headers=vini)
assert r.status_code == 200
assert r.json() == {"processed": 3, "total": 3, "errors": 0}
print("   OK\n")

print("Todos os testes E2E dos endpoints de importação Anki passaram.")

import shutil
shutil.rmtree(SCRATCH, ignore_errors=True)
