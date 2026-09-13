"""
Testes do campo `respondido_em` em POST /study/cards/{id}/answer.

Contexto: o frontend ganhou uma fila de sincronização offline (Nível 2 do
roadmap de resiliência). Uma resposta dada sem internet pode chegar ao
servidor dias depois -- sem esse campo, ela entraria no histórico com a data
de CHEGADA, colapsando dias de estudo em "hoje" (quebra streak/heatmap) e
recalculando o próximo intervalo do SM-2 a partir da data errada.

O servidor não confia cegamente no valor: futuro vira agora, antigo demais é
limitado a MAX_ATRASO_RESPOSTA_DIAS (ver _resolver_respondido_em).
"""
from datetime import datetime, timedelta, timezone

from app.models import User
from app.models.review_history import ReviewHistory
from app.models.review import Review
from app.routers.study import MAX_ATRASO_RESPOSTA_DIAS
from tests.factories import CardFactory, DeckFactory, UserFactory


def _registrar_e_logar(client, db_session, email="respondido_em@estalo.dev"):
    client.post("/auth/register", json={"email": email, "password": "senha-de-teste-2026"})
    login = client.post("/auth/login", data={"username": email, "password": "senha-de-teste-2026"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    user = db_session.query(User).filter(User.email == email).first()
    return auth, user


def _card_do_usuario(db_session, user):
    deck = DeckFactory(owner=user)
    card = CardFactory(deck=deck)
    db_session.commit()
    return card


def _historico(db_session, card_id):
    return (
        db_session.query(ReviewHistory)
        .filter(ReviewHistory.card_id == card_id)
        .order_by(ReviewHistory.id.desc())
        .first()
    )


def test_sem_respondido_em_usa_agora(client, db_session):
    """Caminho de todo cliente online: nada muda."""
    auth, user = _registrar_e_logar(client, db_session)
    card = _card_do_usuario(db_session, user)

    antes = datetime.utcnow()
    resp = client.post(f"/study/cards/{card.id}/answer", json={"quality": 4}, headers=auth)
    depois = datetime.utcnow()

    assert resp.status_code == 200
    hist = _historico(db_session, card.id)
    assert antes - timedelta(seconds=5) <= hist.avaliado_em <= depois + timedelta(seconds=5)


def test_respondido_em_passado_entra_no_historico_com_a_data_original(client, db_session):
    """3 dias offline: a resposta tem que contar no dia em que aconteceu."""
    auth, user = _registrar_e_logar(client, db_session)
    card = _card_do_usuario(db_session, user)

    tres_dias_atras = datetime.utcnow() - timedelta(days=3)
    resp = client.post(
        f"/study/cards/{card.id}/answer",
        json={"quality": 4, "respondido_em": tres_dias_atras.isoformat()},
        headers=auth,
    )

    assert resp.status_code == 200
    hist = _historico(db_session, card.id)
    # Tolerância de 1s só por causa do round-trip de serialização.
    assert abs((hist.avaliado_em - tres_dias_atras).total_seconds()) < 1


def test_respondido_em_passado_ancora_o_proximo_intervalo(client, db_session):
    """O próximo due_date conta a partir de quando respondeu, não de quando
    o servidor recebeu -- senão quem estuda offline revisa sempre atrasado."""
    auth, user = _registrar_e_logar(client, db_session)
    card = _card_do_usuario(db_session, user)

    tres_dias_atras = datetime.utcnow() - timedelta(days=3)
    resp = client.post(
        f"/study/cards/{card.id}/answer",
        json={"quality": 4, "respondido_em": tres_dias_atras.isoformat()},
        headers=auth,
    )

    assert resp.status_code == 200
    review = db_session.query(Review).filter(Review.card_id == card.id).first()
    # Card novo + acerto => interval de 1 dia a partir da resposta,
    # ou seja 3 dias atrás + 1 dia = 2 dias ATRÁS (já vencido, correto).
    esperado = tres_dias_atras + timedelta(days=1)
    assert abs((review.due_date - esperado).total_seconds()) < 2
    assert review.due_date < datetime.utcnow()


def test_respondido_em_no_futuro_vira_agora(client, db_session):
    """Cliente adulterado não pode empurrar due_date/streak pra frente."""
    auth, user = _registrar_e_logar(client, db_session)
    card = _card_do_usuario(db_session, user)

    futuro = datetime.utcnow() + timedelta(days=10)
    resp = client.post(
        f"/study/cards/{card.id}/answer",
        json={"quality": 4, "respondido_em": futuro.isoformat()},
        headers=auth,
    )

    assert resp.status_code == 200
    hist = _historico(db_session, card.id)
    assert hist.avaliado_em <= datetime.utcnow() + timedelta(seconds=5)


def test_respondido_em_antigo_demais_e_limitado_mas_aceito(client, db_session):
    """Não descarta o estudo do usuário -- só impede reescrever histórico
    distante: entra com a data limite da janela."""
    auth, user = _registrar_e_logar(client, db_session)
    card = _card_do_usuario(db_session, user)

    muito_antigo = datetime.utcnow() - timedelta(days=MAX_ATRASO_RESPOSTA_DIAS + 120)
    resp = client.post(
        f"/study/cards/{card.id}/answer",
        json={"quality": 4, "respondido_em": muito_antigo.isoformat()},
        headers=auth,
    )

    assert resp.status_code == 200
    hist = _historico(db_session, card.id)
    limite = datetime.utcnow() - timedelta(days=MAX_ATRASO_RESPOSTA_DIAS)
    assert hist.avaliado_em > muito_antigo            # não usou o valor cru
    assert abs((hist.avaliado_em - limite).total_seconds()) < 5


def test_respondido_em_com_timezone_e_normalizado_pra_utc(client, db_session):
    """O frontend manda ISO com 'Z' (aware); as colunas são naive-UTC."""
    auth, user = _registrar_e_logar(client, db_session)
    card = _card_do_usuario(db_session, user)

    aware = datetime.now(timezone.utc) - timedelta(days=2)
    resp = client.post(
        f"/study/cards/{card.id}/answer",
        json={"quality": 4, "respondido_em": aware.isoformat()},
        headers=auth,
    )

    assert resp.status_code == 200
    hist = _historico(db_session, card.id)
    assert hist.avaliado_em.tzinfo is None
    esperado_naive = aware.astimezone(timezone.utc).replace(tzinfo=None)
    assert abs((hist.avaliado_em - esperado_naive).total_seconds()) < 1


def test_respondido_em_nao_quebra_idempotencia(client, db_session):
    """Reenvio da MESMA resposta (mesmo X-Request-ID) continua não
    duplicando -- é exatamente o que a fila offline faz ao re-tentar."""
    auth, user = _registrar_e_logar(client, db_session)
    card = _card_do_usuario(db_session, user)

    quando = (datetime.utcnow() - timedelta(days=1)).isoformat()
    corpo = {"quality": 4, "respondido_em": quando}
    headers = {**auth, "X-Request-ID": "fila-offline-abc-123"}

    r1 = client.post(f"/study/cards/{card.id}/answer", json=corpo, headers=headers)
    r2 = client.post(f"/study/cards/{card.id}/answer", json=corpo, headers=headers)

    assert r1.status_code == 200 and r2.status_code == 200
    total = (
        db_session.query(ReviewHistory)
        .filter(ReviewHistory.card_id == card.id)
        .count()
    )
    assert total == 1
