"""
Chaos testing do ImportOrchestrator — arquivo corrompido / dados inválidos,
verificando que (1) nada parcial é commitado, (2) o erro fica registrado
no staging, (3) o banco permanece íntegro (nenhum Review órfão, nenhum
Card duplicado por engano).

Nota: os testes de "poison pill" (uma linha ruim no meio de um lote bom)
já existem em test_import_orchestrator.py (raiz do projeto, contra o
estalo.db real) — aqui o foco é o mesmo tipo de garantia, mas em banco
isolado em memória e combinado com uma base pré-existente maior (via
factories), pra caber no espírito de "chaos" pedido nesta suíte nova.
"""
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.models import Card, ImportStagingCard, Review
from app.services.importer.anki_parser import AnkiImportError
from app.services.importer.orchestrator import ImportOrchestrator
from tests.factories import CardFactory, DeckFactory


def _apkg_totalmente_corrompido(caminho: Path) -> None:
    """Zip válido, mas o collection.anki2 dentro dele é lixo binário --
    nem chega a ser um SQLite."""
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("collection.anki2", b"isto definitivamente nao e um banco sqlite")


def _apkg_com_cards_bons_e_um_deck_id_invalido(caminho: Path, tmp_sqlite: Path, deck_id_valido: int) -> None:
    """.apkg válido (parseia sem erro), mas usado de um jeito que força
    uma falha NA PROMOÇÃO (não no parse) -- ver test abaixo, onde uma das
    linhas de staging é adulterada depois pra apontar pra um deck inexistente."""
    conn = sqlite3.connect(tmp_sqlite)
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
    pares = [("Pergunta caótica 1?", "Resposta 1"), ("Pergunta caótica 2?", "Resposta 2")]
    for i, (front, back) in enumerate(pares, start=1):
        conn.execute("INSERT INTO notes VALUES (?, ?, 1, 0, 0, '', ?, ?, 0, 0, '')",
                      (i, f"guid{i}", f"{front}\x1f{back}", front))
        conn.execute("INSERT INTO cards VALUES (?, ?, 1, 0, 0, 0, 2, 2, 10, 15, 2500, 4, 0, 0, 0, 0, 0, '')", (i, i))
    conn.commit()
    conn.close()
    with zipfile.ZipFile(caminho, "w") as z:
        z.write(tmp_sqlite, arcname="collection.anki2")


def _banco_integro(db_session) -> bool:
    """Checagem de integridade referencial simples: todo Review aponta pra
    um Card que existe de verdade. Se isso falhar, o banco ficou num
    estado impossível (exatamente o que a atomicidade deveria impedir)."""
    ids_cards = {c.id for c in db_session.query(Card.id).all()}
    for review in db_session.query(Review).all():
        if review.card_id not in ids_cards:
            return False
    return True


def test_apkg_totalmente_corrompido_nao_deixa_rastro(db_session, tmp_path):
    """AnkiImportError levantado, ZERO linhas em import_staging, banco
    íntegro -- nada parcial."""
    deck = DeckFactory()
    caminho = tmp_path / "corrompido.apkg"
    _apkg_totalmente_corrompido(caminho)

    orch = ImportOrchestrator(db_session)
    with pytest.raises(AnkiImportError):
        orch.initiate_import(user_id=deck.owner_id, deck_id=deck.id, file_path=str(caminho))

    assert db_session.query(ImportStagingCard).count() == 0
    assert db_session.query(Card).filter(Card.deck_id == deck.id).count() == 0
    assert _banco_integro(db_session)


def test_poison_pill_com_base_preexistente_grande(db_session, tmp_path):
    """Um deck já com 300 cards (via factory, simulando uma base real de
    uso), mais um lote de importação onde 1 de 3 linhas é adulterada pra
    apontar pra um deck que não existe. Verifica: as 2 boas promovem, a
    ruim vira status=error com mensagem, e o banco continua íntegro
    (nenhum Review órfão, nenhuma duplicata por engano nos 300 pré-existentes)."""
    deck = DeckFactory()
    CardFactory.create_batch(300, deck=deck)
    db_session.commit()
    total_antes = db_session.query(Card).filter(Card.deck_id == deck.id).count()
    assert total_antes == 300

    tmp_sqlite = tmp_path / "chaos.sqlite"
    apkg = tmp_path / "chaos.apkg"
    _apkg_com_cards_bons_e_um_deck_id_invalido(apkg, tmp_sqlite, deck.id)

    orch = ImportOrchestrator(db_session)
    job_id = orch.initiate_import(user_id=deck.owner_id, deck_id=deck.id, file_path=str(apkg))

    # Adultera uma das linhas de staging pra virar a "veneno": deck_id
    # inexistente dentro do próprio anki_payload.
    linhas = db_session.query(ImportStagingCard).filter(ImportStagingCard.job_id == job_id).all()
    assert len(linhas) == 2
    linha_ruim = linhas[0]
    payload_ruim = dict(linha_ruim.anki_payload)
    payload_ruim["deck_id"] = 999999999
    linha_ruim.anki_payload = payload_ruim
    db_session.commit()

    progresso = orch.process_batch(job_id, batch_size=10)

    assert progresso["total"] == 2
    assert progresso["errors"] == 1
    assert progresso["processed"] == 1

    linha_ruim_final = db_session.query(ImportStagingCard).filter(ImportStagingCard.id == linha_ruim.id).first()
    assert linha_ruim_final.status == "error"
    assert linha_ruim_final.error_message  # mensagem real gravada, não vazia

    # Banco íntegro: os 300 pré-existentes continuam lá, mais só 1 novo
    # (o bom), nenhum órfão.
    total_depois = db_session.query(Card).filter(Card.deck_id == deck.id).count()
    assert total_depois == 301, "esperava 300 pré-existentes + 1 promovido com sucesso"
    assert _banco_integro(db_session)
