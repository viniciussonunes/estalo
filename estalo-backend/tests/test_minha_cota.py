"""
GET /auth/me/quota — a pessoa vendo a própria cota de IA.

O buraco que fecha: existia só /admin/users, que lista TODO MUNDO e exige
ser admin. O usuário comum não tinha como saber quanto tinha usado nem
quanto faltava -- ele descobria o limite BATENDO nele, com um modal
aparecendo no meio de um Tutor.
"""
from datetime import date, timedelta

from app.models.user_quota import DEFAULT_DAILY_LIMIT, UserQuota
from app.services import quota_service

CONTA = {"email": "dono@estalo.dev", "password": "senha-boa-2026"}


def _entrar(client):
    client.post("/auth/register", json=CONTA)
    r = client.post("/auth/login", data={"username": CONTA["email"], "password": CONTA["password"]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_conta_nova_ainda_nao_gastou_nada(client):
    # Quem nunca chamou IA nem tem linha em user_quotas. A tela precisa
    # mostrar algo mesmo assim, não um erro.
    h = _entrar(client)
    r = client.get("/auth/me/quota", headers=h)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["consumido"] == 0
    assert corpo["limite"] == DEFAULT_DAILY_LIMIT
    assert corpo["restante"] == DEFAULT_DAILY_LIMIT


def test_mostra_o_que_ja_foi_gasto(client, db_session):
    h = _entrar(client)
    quota_service.check_and_consume_tokens(1, 1200, db_session)

    corpo = client.get("/auth/me/quota", headers=h).json()
    assert corpo["consumido"] == 1200
    assert corpo["restante"] == corpo["limite"] - 1200


def test_consultar_a_cota_nao_gasta_cota(client, db_session):
    # Óbvio, mas é o tipo de coisa que quebra sem ninguém ver: a tela da
    # conta consulta isso a cada visita.
    h = _entrar(client)
    quota_service.check_and_consume_tokens(1, 500, db_session)
    for _ in range(3):
        client.get("/auth/me/quota", headers=h)
    assert client.get("/auth/me/quota", headers=h).json()["consumido"] == 500


def test_virou_o_dia_zera_antes_de_responder(client, db_session):
    # Sem passar pelo reset, a tela mostraria o consumo de ONTEM até a
    # primeira chamada de IA do dia -- e a pessoa acharia que começou o dia
    # sem cota.
    h = _entrar(client)
    quota_service.check_and_consume_tokens(1, 900, db_session)
    quota = db_session.get(UserQuota, 1)
    quota.last_reset_date = date.today() - timedelta(days=1)
    db_session.commit()

    corpo = client.get("/auth/me/quota", headers=h).json()
    assert corpo["consumido"] == 0


def test_diz_quando_renova(client):
    h = _entrar(client)
    corpo = client.get("/auth/me/quota", headers=h).json()
    # Meia-noite seguinte no relógio do servidor, que é o mesmo que o
    # quota_service usa pra decidir se virou o dia.
    assert corpo["renova_em"].startswith(str(date.today() + timedelta(days=1)))
    assert corpo["renova_em"].endswith("00:00:00")


def test_sem_token_nao_responde(client):
    assert client.get("/auth/me/quota").status_code == 401


def test_um_usuario_nao_ve_a_cota_do_outro(client):
    h1 = _entrar(client)
    client.post("/auth/register", json={"email": "outro@estalo.dev", "password": "outra-senha-2026"})
    r2 = client.post("/auth/login", data={"username": "outro@estalo.dev", "password": "outra-senha-2026"})
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}

    # O endpoint não aceita id de ninguém: quem responde é o dono do token.
    assert client.get("/auth/me/quota", headers=h1).status_code == 200
    assert client.get("/auth/me/quota", headers=h2).status_code == 200
    assert client.get("/auth/me/quota", headers=h2).json()["consumido"] == 0
