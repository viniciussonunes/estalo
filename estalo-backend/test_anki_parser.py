"""Teste do parser de .apkg (app/services/importer/anki_parser.py).

Não há Anki Desktop disponível neste ambiente pra gerar um .apkg real, então
este teste CONSTRÓI um fixture sintético fiel ao schema real do Anki (tabelas
col/notes/cards, JSON de models com um tipo Basic, um "Basic e invertido" e
um Cloze) em vez de usar um export de verdade. Se algum dia rodar isso com um
.apkg exportado pelo Anki Desktop de verdade, o comportamento esperado é o
mesmo: cards do tipo Basic entram, o resto é pulado e contado.
"""
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from app.services.importer.anki_parser import AnkiImportError, parse_apkg

SCRATCH = Path(tempfile.mkdtemp(prefix="estalo_test_fixtures_"))


def _criar_sqlite_colecao(caminho_sqlite: Path) -> None:
    """Monta um collection.anki2 com o schema mínimo real do Anki. 5 notas
    Basic (em escopo), 1 Basic-e-invertido (2 templates, fora de escopo),
    1 Cloze (fora de escopo), 1 nota com note type desconhecido (mid que
    não existe em col.models)."""
    if caminho_sqlite.exists():
        caminho_sqlite.unlink()

    conn = sqlite3.connect(caminho_sqlite)
    conn.executescript("""
        CREATE TABLE col (
            id INTEGER PRIMARY KEY, crt INTEGER, mod INTEGER, scm INTEGER,
            ver INTEGER, dty INTEGER, usn INTEGER, ls INTEGER,
            conf TEXT, models TEXT, decks TEXT, dconf TEXT, tags TEXT
        );
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY, guid TEXT, mid INTEGER, mod INTEGER,
            usn INTEGER, tags TEXT, flds TEXT, sfld TEXT, csum INTEGER,
            flags INTEGER, data TEXT
        );
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER, ord INTEGER,
            mod INTEGER, usn INTEGER, type INTEGER, queue INTEGER,
            due INTEGER, ivl INTEGER, factor INTEGER, reps INTEGER,
            lapses INTEGER, left INTEGER, odue INTEGER, odid INTEGER,
            flags INTEGER, data TEXT
        );
    """)

    modelos = {
        "1": {"type": 0, "tmpls": [{"name": "Card 1"}]},                              # Basic
        "2": {"type": 0, "tmpls": [{"name": "Card 1"}, {"name": "Card 2"}]},          # Basic (e invertido)
        "3": {"type": 1, "tmpls": [{"name": "Cloze"}]},                                # Cloze
        # mid 99 propositalmente ausente daqui -> "tipo de nota desconhecido"
    }
    conn.execute(
        "INSERT INTO col (id, crt, mod, scm, ver, dty, usn, ls, conf, models, decks, dconf, tags) "
        "VALUES (1,0,0,0,11,0,0,0,'{}',?,'{}','{}','')",
        (json.dumps(modelos),),
    )

    notas_basic = [
        ("Qual a capital da França?", "Paris"),
        ("Qual a capital da Itália?", "Roma"),
        ("Qual a capital do Japão?", "Tóquio"),
        ("Qual a capital de Portugal?", "Lisboa"),
        ("Qual a capital da Alemanha?", "Berlim"),
    ]
    nid = 1
    cid = 1
    for front, back in notas_basic:
        conn.execute(
            "INSERT INTO notes (id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data) "
            "VALUES (?, ?, 1, 0, 0, ' geografia ', ?, ?, 0, 0, '')",
            (nid, f"guid{nid}", f"{front}\x1f{back}", front),
        )
        conn.execute(
            "INSERT INTO cards (id, nid, did, ord, mod, usn, type, queue, due, ivl, factor, "
            "reps, lapses, left, odue, odid, flags, data) "
            "VALUES (?, ?, 1, 0, 0, 0, 2, 2, 10, 15, 2500, 4, 0, 0, 0, 0, 0, '')",
            (cid, nid),
        )
        nid += 1
        cid += 1

    # Basic (e invertido) -- 1 nota, fora de escopo
    conn.execute(
        "INSERT INTO notes (id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data) "
        "VALUES (?, 'guid_rev', 2, 0, 0, '', 'Front\x1fBack', 'Front', 0, 0, '')",
        (nid,),
    )
    conn.execute(
        "INSERT INTO cards (id, nid, did, ord, mod, usn, type, queue, due, ivl, factor, "
        "reps, lapses, left, odue, odid, flags, data) "
        "VALUES (?, ?, 1, 0, 0, 0, 2, 2, 10, 15, 2500, 4, 0, 0, 0, 0, 0, '')",
        (cid, nid),
    )
    nid += 1
    cid += 1

    # Cloze -- 1 nota, fora de escopo
    conn.execute(
        "INSERT INTO notes (id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data) "
        "VALUES (?, 'guid_cloze', 3, 0, 0, '', '{{c1::Paris}} é a capital da França\x1f', '', 0, 0, '')",
        (nid,),
    )
    conn.execute(
        "INSERT INTO cards (id, nid, did, ord, mod, usn, type, queue, due, ivl, factor, "
        "reps, lapses, left, odue, odid, flags, data) "
        "VALUES (?, ?, 1, 0, 0, 0, 2, 2, 10, 15, 2500, 4, 0, 0, 0, 0, 0, '')",
        (cid, nid),
    )
    nid += 1
    cid += 1

    # Note type desconhecido (mid=99 não existe em col.models) -- fora de escopo
    conn.execute(
        "INSERT INTO notes (id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data) "
        "VALUES (?, 'guid_desconhecido', 99, 0, 0, '', 'X\x1fY', 'X', 0, 0, '')",
        (nid,),
    )
    conn.execute(
        "INSERT INTO cards (id, nid, did, ord, mod, usn, type, queue, due, ivl, factor, "
        "reps, lapses, left, odue, odid, flags, data) "
        "VALUES (?, ?, 1, 0, 0, 0, 2, 2, 10, 15, 2500, 4, 0, 0, 0, 0, 0, '')",
        (cid, nid),
    )

    conn.commit()
    conn.close()


def _construir_apkg(caminho_apkg: Path) -> None:
    """collection.anki2 puro, zipado sem compressão extra — schema legado."""
    caminho_sqlite = caminho_apkg.parent / "collection.anki2"
    _criar_sqlite_colecao(caminho_sqlite)
    with zipfile.ZipFile(caminho_apkg, "w") as z:
        z.write(caminho_sqlite, arcname="collection.anki2")
    caminho_sqlite.unlink()


def _construir_apkg_zstd(caminho_apkg: Path) -> None:
    """collection.anki21b — mesmo conteúdo, comprimido em zstd dentro do
    zip, formato padrão de export desde o Anki 23.10."""
    import zstandard

    caminho_sqlite = caminho_apkg.parent / "collection_zstd.anki2"
    _criar_sqlite_colecao(caminho_sqlite)
    comprimido = zstandard.ZstdCompressor().compress(caminho_sqlite.read_bytes())
    with zipfile.ZipFile(caminho_apkg, "w") as z:
        z.writestr("collection.anki21b", comprimido)
    caminho_sqlite.unlink()


apkg_valido = SCRATCH / "deck_teste.apkg"
_construir_apkg(apkg_valido)

print("1) Parse do .apkg sintético -- número de cards bate com o esperado...")
resultado = parse_apkg(apkg_valido)
print(f"   importados: {len(resultado.cards)} | pulados: {resultado.pulados} | motivos: {resultado.motivos_pulados}")
assert len(resultado.cards) == 5, f"esperava 5 cards Basic, veio {len(resultado.cards)}"
assert resultado.pulados == 3, f"esperava 3 pulados, veio {resultado.pulados}"
assert resultado.motivos_pulados == {"cloze_ou_tipo_customizado": 2, "tipo_de_nota_desconhecido": 1}
print("   OK\n")

print("2) Conteúdo dos cards importados está correto (front/back/tags/ease/interval crus)...")
primeiro = next(c for c in resultado.cards if c["front"] == "Qual a capital da França?")
assert primeiro["back"] == "Paris"
assert primeiro["tags"] == ["geografia"]
assert primeiro["ease"] == 2500       # cru, sem dividir por 1000
assert primeiro["interval"] == 15     # cru, sem interpretar sinal
print("   OK\n")

print("2b) Mesmo conteúdo em collection.anki21b (zstd) -- formato padrão do Anki 23.10+...")
apkg_zstd = SCRATCH / "deck_teste_zstd.apkg"
_construir_apkg_zstd(apkg_zstd)
resultado_zstd = parse_apkg(apkg_zstd)
assert len(resultado_zstd.cards) == 5 and resultado_zstd.pulados == 3
print("   OK\n")

print("3) Arquivo que não é um zip -> AnkiImportError...")
nao_zip = SCRATCH / "nao_e_zip.apkg"
nao_zip.write_bytes(b"isso claramente nao e um zip valido")
try:
    parse_apkg(nao_zip)
    raise SystemExit("ERRO: deveria ter levantado AnkiImportError")
except AnkiImportError as e:
    print(f"   OK -- {e}\n")

print("4) Zip válido mas sem nenhum collection.anki* -> AnkiImportError...")
zip_vazio = SCRATCH / "zip_sem_colecao.apkg"
with zipfile.ZipFile(zip_vazio, "w") as z:
    z.writestr("media", "{}")
try:
    parse_apkg(zip_vazio)
    raise SystemExit("ERRO: deveria ter levantado AnkiImportError")
except AnkiImportError as e:
    print(f"   OK -- {e}\n")

print("5) collection.anki2 corrompido (não é SQLite de verdade) -> AnkiImportError...")
zip_corrompido = SCRATCH / "colecao_corrompida.apkg"
with zipfile.ZipFile(zip_corrompido, "w") as z:
    z.writestr("collection.anki2", b"bytes aleatorios, nao e um sqlite")
try:
    parse_apkg(zip_corrompido)
    raise SystemExit("ERRO: deveria ter levantado AnkiImportError")
except AnkiImportError as e:
    print(f"   OK -- {e}\n")

print("6) Arquivo inexistente -> AnkiImportError (não FileNotFoundError cru)...")
try:
    parse_apkg(SCRATCH / "isso_nao_existe.apkg")
    raise SystemExit("ERRO: deveria ter levantado AnkiImportError")
except AnkiImportError as e:
    print(f"   OK -- {e}\n")

print("7) Diretório temporário de extração não sobrevive à chamada (segurança)...")
antes = {p for p in Path(tempfile.gettempdir()).glob("estalo_anki_import_*")}
parse_apkg(apkg_valido)
depois = {p for p in Path(tempfile.gettempdir()).glob("estalo_anki_import_*")}
assert depois == antes, f"sobrou diretório temporário: {depois - antes}"
print("   OK -- nenhum diretório temporário deixado pra trás\n")

print("Todos os testes do parser de Anki passaram.")

# limpeza dos fixtures deste teste
import shutil
shutil.rmtree(SCRATCH, ignore_errors=True)
