"""
Ouvir, fase 3: o áudio guardado no servidor (Vercel Blob privado).

O que estes testes seguram, e por quê:

  - **Bloco guardado não gasta cota.** É o que faz o segundo aparelho
    baixar o áudio em vez de gravar de novo. Se o servidor regravasse,
    cada aparelho pagaria a locução inteira outra vez.
  - **O Blob é bônus, nunca requisito.** O plano Hobby recusa gravações
    ao estourar a cota do mês, sem cobrar. Recusou: o áudio chega ao
    aparelho do mesmo jeito (comportamento da fase 1).
  - **O app antigo continua recebendo PCM.** Ele trata a resposta como
    PCM; um MP3 tocaria como chiado. Só quem pede formato=mp3 recebe MP3.
  - **Nada fica órfão no Blob.** Remover o áudio, refazer a conversa e
    apagar o deck apagam os arquivos -- depois do commit, pra um rollback
    não levar o arquivo junto. (Apagar a PASTA hoje não apaga os decks de
    dentro: eles vão pra raiz, com o áudio. Visto em 27/11/2026; é outro
    assunto. Quando a pasta passar a apagar os decks pelo ORM, o áudio
    sai junto pela relação Deck.audio, sem código novo aqui.)
  - **O roteiro sai junto com o deck também no SQLite.** Antes só a FK do
    Postgres cuidava disso (débito técnico da fase 1).

O Blob é sempre simulado: a suíte não fala com a rede.
"""
from unittest.mock import patch

from app.models import DeckAudio
from app.services import audio_storage

ROTEIRO = [
    {"titulo": "Abertura", "falas": [{"quem": "Rafael", "texto": "Oi?"}, {"quem": "Beatriz", "texto": "Olá."}]},
    {"titulo": "Fim", "falas": [{"quem": "Rafael", "texto": "E aí?"}, {"quem": "Beatriz", "texto": "Fim."}]},
]
PCM = b"\x10\x00\x20\x00" * 6000          # 12.000 amostras de 16 bits
MP3_GUARDADO = b"ID3-mp3-guardado"


def _autenticar(client, email):
    client.post("/auth/register", json={"email": email, "password": "senha-de-teste-2026"})
    login = client.post("/auth/login", data={"username": email, "password": "senha-de-teste-2026"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _deck_com_roteiro(client, auth):
    corpo = {"title": "Farmacologia"}
    deck = client.post("/decks", json=corpo, headers=auth).json()
    client.post(f"/decks/{deck['id']}/cards", json={"front": "P", "back": "R"}, headers=auth)
    with patch("app.routers.audio.gerar_roteiro", return_value=ROTEIRO):
        client.post(f"/decks/{deck['id']}/audio/roteiro", headers=auth)
    return deck


def _tts():
    return patch("app.routers.audio.sintetizar_bloco", return_value=(PCM, 24000))


def _blob_guarda():
    """Blob que aceita: devolve uma URL previsível por caminho."""
    return patch.object(audio_storage, "guardar", side_effect=lambda caminho, mp3: f"https://blob.test/{caminho}")


# ------------------------------------------------------------- gravar

def test_mp3_sem_blob_ainda_entrega_o_audio(client):
    """Blob indisponível (sem credencial, cota do mês estourada): o bloco
    chega ao aparelho igual -- só não fica no servidor."""
    auth = _autenticar(client, "f3_semblob@estalo.dev")
    deck = _deck_com_roteiro(client, auth)
    with _tts(), patch.object(audio_storage, "guardar", return_value=None):
        r = client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=mp3", headers=auth)

    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.headers["x-origem"] == "gravado"
    assert r.headers["x-amostras"] == "12000"
    assert len(r.content) > 0 and r.content != PCM
    assert client.get(f"/decks/{deck['id']}/audio", headers=auth).json()["blocos_no_servidor"] == 0


def test_bloco_gravado_fica_no_servidor(client, db_session):
    auth = _autenticar(client, "f3_guarda@estalo.dev")
    deck = _deck_com_roteiro(client, auth)
    with _tts(), _blob_guarda() as guardar:
        client.post(f"/decks/{deck['id']}/audio/bloco/1?formato=mp3", headers=auth)

    caminho = guardar.call_args.args[0]
    # ouvir/u{usuário}/d{deck}/a{roteiro}-{versão}/b{bloco}.mp3 -- a versão
    # no caminho é o que impede um roteiro reescrito de herdar arquivo.
    import re
    assert re.fullmatch(rf"ouvir/u\d+/d{deck['id']}/a\d+-\d+/b1\.mp3", caminho), caminho
    audio = db_session.query(DeckAudio).filter(DeckAudio.deck_id == deck["id"]).first()
    db_session.refresh(audio)
    assert audio.blocos_mp3[0] is None
    assert audio.blocos_mp3[1]["amostras"] == 12000 and audio.blocos_mp3[1]["taxa"] == 24000
    assert client.get(f"/decks/{deck['id']}/audio", headers=auth).json()["blocos_no_servidor"] == 1


def test_bloco_guardado_nao_gasta_cota_de_novo(client):
    """O segundo aparelho: pede o mesmo bloco e recebe o guardado, sem TTS."""
    auth = _autenticar(client, "f3_reuso@estalo.dev")
    deck = _deck_com_roteiro(client, auth)
    with _tts(), _blob_guarda():
        client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=mp3", headers=auth)

    with _tts() as tts, patch.object(audio_storage, "ler", return_value=MP3_GUARDADO):
        r = client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=mp3", headers=auth)

    tts.assert_not_called()
    assert r.content == MP3_GUARDADO
    assert r.headers["x-origem"] == "servidor"
    assert r.headers["x-amostras"] == "12000"


def test_bloco_guardado_que_nao_le_e_gravado_de_novo(client):
    """Arquivo sumido do Blob: melhor gastar cota que deixar sem áudio."""
    auth = _autenticar(client, "f3_sumiu@estalo.dev")
    deck = _deck_com_roteiro(client, auth)
    with _tts(), _blob_guarda():
        client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=mp3", headers=auth)

    with _tts() as tts, _blob_guarda(), patch.object(audio_storage, "ler", return_value=None):
        r = client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=mp3", headers=auth)

    tts.assert_called_once()
    assert r.headers["x-origem"] == "gravado"


def test_app_antigo_continua_recebendo_pcm(client):
    """Sem formato=mp3 (app da fase 1 em cache): PCM cru, como sempre --
    e o bloco é guardado mesmo assim, pro próximo aparelho."""
    auth = _autenticar(client, "f3_legado@estalo.dev")
    deck = _deck_com_roteiro(client, auth)
    with _tts(), _blob_guarda() as guardar:
        r = client.post(f"/decks/{deck['id']}/audio/bloco/0", headers=auth)

    assert r.content == PCM
    assert r.headers["content-type"] == "application/octet-stream"
    guardar.assert_called_once()


def test_app_antigo_nao_recebe_mp3_guardado(client):
    """Mesmo com o bloco no Blob, o app antigo recebe PCM (ele não
    decodificaria o MP3) -- então ele grava, e paga, como na fase 1."""
    auth = _autenticar(client, "f3_legado2@estalo.dev")
    deck = _deck_com_roteiro(client, auth)
    with _tts(), _blob_guarda():
        client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=mp3", headers=auth)
    with _tts() as tts, _blob_guarda(), patch.object(audio_storage, "ler") as ler:
        r = client.post(f"/decks/{deck['id']}/audio/bloco/0", headers=auth)

    ler.assert_not_called()
    tts.assert_called_once()
    assert r.content == PCM


def test_formato_invalido_e_422(client):
    auth = _autenticar(client, "f3_formato@estalo.dev")
    deck = _deck_com_roteiro(client, auth)
    r = client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=wav", headers=auth)
    assert r.status_code == 422


def test_taxa_e_amostras_chegam_ao_javascript(client):
    """Sem expose_headers, o navegador esconde X-Amostras do app e a duração
    do episódio sai errada (o MP3 não diz a duração sem decodificar)."""
    auth = _autenticar(client, "f3_cors@estalo.dev")
    deck = _deck_com_roteiro(client, auth)
    with _tts(), patch.object(audio_storage, "guardar", return_value=None):
        r = client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=mp3",
                        headers={**auth, "Origin": "http://localhost:5173"})
    expostos = {h.strip().lower() for h in r.headers.get("access-control-expose-headers", "").split(",")}
    assert {"x-taxa-amostragem", "x-amostras", "x-origem"} <= expostos


# ------------------------------------------------------------- refazer

def test_refazer_apaga_os_blocos_e_muda_a_versao(client, db_session):
    auth = _autenticar(client, "f3_refazer@estalo.dev")
    deck = _deck_com_roteiro(client, auth)
    with _tts(), _blob_guarda():
        client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=mp3", headers=auth)
    antes = client.get(f"/decks/{deck['id']}/audio", headers=auth).json()["criado_em"]

    with patch("app.routers.audio.gerar_roteiro", return_value=ROTEIRO), \
         patch.object(audio_storage, "apagar") as apagar:
        r = client.post(f"/decks/{deck['id']}/audio/roteiro?refazer=true", headers=auth).json()

    apagado = apagar.call_args.args[0]
    assert len(apagado) == 1 and apagado[0].endswith("/b0.mp3")
    assert r["blocos_no_servidor"] == 0
    assert r["criado_em"] != antes


# ------------------------------------------------------------- apagar

def _deck_com_bloco_guardado(client, auth):
    deck = _deck_com_roteiro(client, auth)
    with _tts(), _blob_guarda():
        client.post(f"/decks/{deck['id']}/audio/bloco/0?formato=mp3", headers=auth)
        client.post(f"/decks/{deck['id']}/audio/bloco/1?formato=mp3", headers=auth)
    return deck


def test_remover_o_audio_apaga_do_blob(client):
    auth = _autenticar(client, "f3_remover@estalo.dev")
    deck = _deck_com_bloco_guardado(client, auth)
    with patch.object(audio_storage, "apagar") as apagar:
        client.delete(f"/decks/{deck['id']}/audio", headers=auth)
    assert sorted(u[-6:] for u in apagar.call_args.args[0]) == ["b0.mp3", "b1.mp3"]


def test_apagar_o_deck_apaga_roteiro_e_blob(client, db_session):
    """O débito da fase 1: no SQLite o roteiro ficava órfão."""
    auth = _autenticar(client, "f3_deck@estalo.dev")
    deck = _deck_com_bloco_guardado(client, auth)
    with patch.object(audio_storage, "apagar") as apagar:
        assert client.delete(f"/decks/{deck['id']}", headers=auth).status_code == 204

    db_session.expire_all()
    assert db_session.query(DeckAudio).filter(DeckAudio.deck_id == deck["id"]).count() == 0
    assert len(apagar.call_args.args[0]) == 2


def test_rollback_nao_apaga_do_blob(db_session):
    """O arquivo só sai do Blob se o banco confirmou a exclusão."""
    audio = db_session.query(DeckAudio).first()
    if audio is None:
        from tests.factories import DeckFactory
        deck = DeckFactory()
        audio = DeckAudio(deck_id=deck.id, roteiro=ROTEIRO, content_hash="x",
                          blocos_mp3=[{"url": "https://blob.test/x.mp3", "amostras": 1, "taxa": 1, "bytes": 1}])
        db_session.add(audio)
        db_session.commit()
    with patch.object(audio_storage, "apagar") as apagar:
        db_session.delete(audio)
        db_session.flush()
        db_session.rollback()
    apagar.assert_not_called()


# ------------------------------------------------------------- unidades

def test_codificar_mp3_de_verdade():
    """lameenc real: sai um MP3 (frame sync 0xFFE no começo de um quadro)
    bem menor que o PCM."""
    pcm = b"\x00\x10" * 24000  # 1s a 24 kHz
    mp3 = audio_storage.codificar_mp3(pcm, 24000)
    assert 0 < len(mp3) < len(pcm) / 4
    assert any(mp3[i] == 0xFF and mp3[i + 1] & 0xE0 == 0xE0 for i in range(min(len(mp3) - 1, 2000)))


def test_sem_credencial_nem_tenta_falar_com_o_blob(monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    with patch("vercel.blob.sync.put_blob") as put:
        assert audio_storage.guardar("x/y.mp3", b"abc") is None
    put.assert_not_called()


def test_falha_do_blob_vira_nao_guardou(monkeypatch):
    """Cota do Hobby estourada, Blob fora do ar: nunca propaga."""
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "falso")
    with patch("vercel.blob.sync.put_blob", side_effect=RuntimeError("store suspended")):
        assert audio_storage.guardar("x/y.mp3", b"abc") is None
    with patch("vercel.blob.sync.delete_blob", side_effect=RuntimeError("rate limited")):
        audio_storage.apagar(["https://blob.test/x.mp3"])  # não levanta
