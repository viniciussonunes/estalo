"""Teste do ImportOrchestrator (app/services/importer/orchestrator.py).

Usuários/decks são criados via a API real (TestClient), mas o orquestrador
em si é exercitado direto via SessionLocal + ImportOrchestrator -- sem
passar pelo FastAPI em nenhum momento, provando que ele não depende disso.
"""
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import Card, ImportStagingCard, Review
from app.services.importer.orchestrator import DeckNaoAutorizadoError, ImportOrchestrator
from app.services.importer.anki_parser import AnkiImportError

client = TestClient(app)
SCRATCH = Path(tempfile.mkdtemp(prefix="estalo_test_orchestrator_"))


def logar(email, senha="senha123"):
    client.post("/auth/register", json={"email": email, "password": senha})
    r = client.post("/auth/login", data={"username": email, "password": senha})
    token = r.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return {"Authorization": f"Bearer {token}"}, me["id"]


def _construir_apkg(caminho_apkg: Path, pares: list[tuple[str, str]]) -> None:
    """.apkg sintético só com notas Basic -- o parser já é testado à
    exaustão em test_anki_parser.py, aqui só precisamos de cards de verdade
    fluindo pelo orquestrador."""
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
    conn.execute(
        "INSERT INTO col VALUES (1,0,0,0,11,0,0,0,'{}',?,'{}','{}','')",
        (json.dumps(modelos),),
    )
    for i, (front, back) in enumerate(pares, start=1):
        conn.execute(
            "INSERT INTO notes VALUES (?, ?, 1, 0, 0, '', ?, ?, 0, 0, '')",
            (i, f"guid{i}", f"{front}\x1f{back}", front),
        )
        conn.execute(
            "INSERT INTO cards VALUES (?, ?, 1, 0, 0, 0, 2, 2, 10, 15, 2500, 4, 0, 0, 0, 0, 0, '')",
            (i, i),
        )
    conn.commit()
    conn.close()

    with zipfile.ZipFile(caminho_apkg, "w") as z:
        z.write(caminho_sqlite, arcname="collection.anki2")
    caminho_sqlite.unlink()


vini_auth, vini_id = logar("orch_vini@estalo.dev")
outro_auth, outro_id = logar("orch_outro@estalo.dev")

deck_vini = client.post("/decks", json={"title": "Deck Import Vini"}, headers=vini_auth).json()
deck_outro = client.post("/decks", json={"title": "Deck Import Outro"}, headers=outro_auth).json()

db = SessionLocal()
orch = ImportOrchestrator(db)

print("1) initiate_import recusa deck de outro usuário (segurança)...")
apkg1 = SCRATCH / "deck1.apkg"
_construir_apkg(apkg1, [("Capital da França?", "Paris")])
try:
    orch.initiate_import(user_id=vini_id, deck_id=deck_outro["id"], file_path=str(apkg1))
    raise SystemExit("ERRO: deveria ter recusado")
except DeckNaoAutorizadoError:
    print("   OK -- DeckNaoAutorizadoError levantado\n")

print("2) initiate_import com .apkg inválido propaga AnkiImportError, sem gravar staging...")
apkg_invalido = SCRATCH / "invalido.apkg"
apkg_invalido.write_bytes(b"lixo")
antes = db.query(ImportStagingCard).count()
try:
    orch.initiate_import(user_id=vini_id, deck_id=deck_vini["id"], file_path=str(apkg_invalido))
    raise SystemExit("ERRO: deveria ter levantado AnkiImportError")
except AnkiImportError:
    depois = db.query(ImportStagingCard).count()
    assert depois == antes, "não deveria ter gravado staging num import que falhou no parse"
    print("   OK -- AnkiImportError levantado, staging intacto\n")

print("3) initiate_import válido -> job_id + staging populado com status=pending...")
pares = [("Capital da França?", "Paris"), ("Capital da Itália?", "Roma"), ("Capital do Japão?", "Tóquio")]
apkg_valido = SCRATCH / "valido.apkg"
_construir_apkg(apkg_valido, pares)
job_id = orch.initiate_import(user_id=vini_id, deck_id=deck_vini["id"], file_path=str(apkg_valido))
assert isinstance(job_id, str) and len(job_id) > 0
linhas_staging = db.query(ImportStagingCard).filter(ImportStagingCard.job_id == job_id).all()
assert len(linhas_staging) == 3
assert all(l.status == "pending" for l in linhas_staging)
print(f"   OK -- job_id={job_id}, 3 linhas pending\n")

print("4) process_batch promove tudo -- Card+Review reais criados, progresso correto...")
progresso = orch.process_batch(job_id, batch_size=200)
print("   progresso:", progresso)
assert progresso == {"processed": 3, "total": 3, "errors": 0}

cards_criados = db.query(Card).filter(Card.deck_id == deck_vini["id"], Card.source == "anki_import").all()
assert len(cards_criados) == 3
paris = next(c for c in cards_criados if c.back == "Paris")
review_paris = db.query(Review).filter(Review.card_id == paris.id).first()
assert review_paris is not None
assert review_paris.user_id == vini_id
assert review_paris.ease_factor == 2.5     # 2500/1000
assert review_paris.interval == 15
assert review_paris.repetitions == 1        # interval>0 -> heurística "Validando"
assert paris.content_hash is not None
print("   OK\n")

print("5) Reimportar o MESMO .apkg no mesmo deck -> tudo vira duplicate, sem Card novo...")
job_id_2 = orch.initiate_import(user_id=vini_id, deck_id=deck_vini["id"], file_path=str(apkg_valido))
progresso_2 = orch.process_batch(job_id_2, batch_size=200)
print("   progresso (reimport):", progresso_2)
assert progresso_2 == {"processed": 3, "total": 3, "errors": 0}
total_cards_no_deck = db.query(Card).filter(Card.deck_id == deck_vini["id"]).count()
assert total_cards_no_deck == 3, "reimport não deveria ter criado cards duplicados"
status_job_2 = {l.status for l in db.query(ImportStagingCard).filter(ImportStagingCard.job_id == job_id_2).all()}
assert status_job_2 == {"duplicate"}
print("   OK -- deduplicado corretamente via content_hash\n")

print("6) Lote com 1 linha 'veneno' -- as boas se promovem, só a ruim vira error...")
apkg_misto = SCRATCH / "misto.apkg"
_construir_apkg(apkg_misto, [("Capital da Espanha?", "Madrid"), ("Capital de Portugal?", "Lisboa")])
job_id_3 = orch.initiate_import(user_id=vini_id, deck_id=deck_vini["id"], file_path=str(apkg_misto))

# Injeta uma 3ª linha de staging propositalmente quebrada nesse mesmo job
# (payload sem "front"/"back", simulando corrupção) -- feito direto no
# banco pra forçar exatamente o cenário de "uma linha ruim no meio do lote".
linha_ruim = ImportStagingCard(
    job_id=job_id_3, front="", back="", tags="",
    anki_payload={"deck_id": deck_vini["id"]},  # sem front/back -> mapear_para_estalo lida, mas sem conteúdo real
    status="pending",
)
db.add(linha_ruim)
db.commit()

# Torna essa linha genuinamente inválida: deck_id apontando pra um deck que não existe
linha_ruim.anki_payload = {"front": "X", "back": "Y", "tags": [], "ease": 2500, "interval": 5, "deck_id": 999999}
db.add(linha_ruim)
db.commit()

progresso_3 = orch.process_batch(job_id_3, batch_size=200)
print("   progresso (lote misto):", progresso_3)
assert progresso_3["total"] == 3
assert progresso_3["errors"] == 1
assert progresso_3["processed"] == 2

madrid = db.query(Card).filter(Card.deck_id == deck_vini["id"], Card.back == "Madrid").first()
lisboa = db.query(Card).filter(Card.deck_id == deck_vini["id"], Card.back == "Lisboa").first()
assert madrid is not None and lisboa is not None, "as linhas boas deveriam ter sido promovidas mesmo com uma ruim no lote"

linha_ruim_final = db.query(ImportStagingCard).filter(ImportStagingCard.id == linha_ruim.id).first()
assert linha_ruim_final.status == "error"
assert linha_ruim_final.error_message  # alguma mensagem foi gravada
print(f"   OK -- erro registrado: {linha_ruim_final.error_message[:80]}\n")

db.close()
print("Todos os testes do ImportOrchestrator passaram.")

import shutil
shutil.rmtree(SCRATCH, ignore_errors=True)
