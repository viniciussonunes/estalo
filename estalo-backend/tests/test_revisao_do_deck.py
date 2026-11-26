"""
`vence_em` na listagem do deck: a base da revisão do deck e do treino.

Por que existe, e por que é uma DATA e não um "venceu?" pronto:

  - **"Estudar hoje (5)" abria o deck inteiro.** O Aprender carregava todos
    os cards e cada resposta valia como revisão espaçada, vencida ou não.
    Medido com o SM-2 real: card novo aberto duas vezes no mesmo dia virava
    Dominado (6 dias) sem esperar intervalo nenhum; card que só venceria em
    6 dias ia pra 16 com 1 dia passado.
  - **A revisão do deck tem que funcionar offline.** Deck baixado abre da
    cópia no aparelho, e o botão de estudar não pode esperar o servidor
    (e2e/rede-lenta.spec.js). Por isso quem monta a revisão é o app, a
    partir desta lista -- e um booleano calculado no dia do download
    estaria errado no dia seguinte. Com a data, o app decide na hora.
  - **O botão e a sessão batem.** O botão do deck mostra críticos + hoje
    das estatísticas; a revisão traz os cards com vence_em <= hoje. Os dois
    têm que contar o mesmo conjunto -- o Estalo já teve um badge dizendo
    "N pendentes" com a fila vazia (fuso horário).
"""
from datetime import date, datetime, timedelta

from app.models import User
from tests.factories import CardFactory, DeckFactory, ReviewFactory

TZ = {"X-User-Timezone": "America/Sao_Paulo"}


def _hoje_sp() -> date:
    return (datetime.utcnow() - timedelta(hours=3)).date()


def _login(client, db_session, email):
    client.post("/auth/register", json={"email": email, "password": "senha-de-teste-2026"})
    login = client.post("/auth/login", data={"username": email, "password": "senha-de-teste-2026"})
    auth = {"Authorization": f"Bearer {login.json()['access_token']}", **TZ}
    return auth, db_session.query(User).filter(User.email == email).first()


def _deck_misto(db_session, user):
    """15 cards: 2 críticos, 3 vencendo hoje, 6 em dia (futuro), 4 novos."""
    deck = DeckFactory(owner=user)
    agora = datetime.utcnow()
    h = _hoje_sp()
    ids = {"critico": [], "hoje": [], "futuro": [], "novo": []}
    for _ in range(2):
        c = CardFactory(deck=deck)
        ReviewFactory(user=user, card=c, repetitions=2, due_date=agora - timedelta(days=3))
        ids["critico"].append(c.id)
    for _ in range(3):
        c = CardFactory(deck=deck)
        # meio-dia em São Paulo = 15h UTC; usar "agora" deixaria o teste
        # dependente da hora em que roda
        ReviewFactory(user=user, card=c, repetitions=1, due_date=datetime(h.year, h.month, h.day, 15, 0))
        ids["hoje"].append(c.id)
    for _ in range(6):
        c = CardFactory(deck=deck)
        ReviewFactory(user=user, card=c, repetitions=2, due_date=agora + timedelta(days=6))
        ids["futuro"].append(c.id)
    for _ in range(4):
        ids["novo"].append(CardFactory(deck=deck).id)
    db_session.commit()
    return deck, ids


def _vence_em(client, auth, deck_id):
    return {c["id"]: c["vence_em"] for c in client.get(f"/decks/{deck_id}/cards", headers=auth).json()}


def test_vence_em_por_situacao_do_card(client, db_session):
    auth, user = _login(client, db_session, "vence_em@estalo.dev")
    deck, ids = _deck_misto(db_session, user)
    hoje = _hoje_sp().isoformat()

    v = _vence_em(client, auth, deck.id)

    assert all(v[i] < hoje for i in ids["critico"])
    assert all(v[i] == hoje for i in ids["hoje"])
    assert all(v[i] > hoje for i in ids["futuro"])
    assert all(v[i] is None for i in ids["novo"])


def test_vencidos_da_lista_batem_com_o_numero_do_botao(client, db_session):
    """O app monta a revisão do deck com vence_em <= hoje; o botão mostra
    criticos + hoje das estatísticas. Os dois têm que contar igual."""
    auth, user = _login(client, db_session, "vence_em_botao@estalo.dev")
    deck, _ = _deck_misto(db_session, user)
    hoje = _hoje_sp().isoformat()

    v = _vence_em(client, auth, deck.id)
    stats = client.get(f"/study/decks/{deck.id}/stats", headers=auth).json()

    vencidos = [i for i, d in v.items() if d is not None and d <= hoje]
    assert len(vencidos) == stats["criticos"] + stats["hoje"] == 5


def test_card_que_errou_vence_hoje(client, db_session):
    """Errar zera repetitions e põe due=agora (Crítico Imediato): tem que
    entrar na revisão, não ser confundido com card novo."""
    auth, user = _login(client, db_session, "vence_em_erro@estalo.dev")
    deck = DeckFactory(owner=user)
    c = CardFactory(deck=deck)
    ReviewFactory(user=user, card=c, repetitions=0, due_date=datetime.utcnow())
    db_session.commit()

    assert _vence_em(client, auth, deck.id)[c.id] == _hoje_sp().isoformat()


def test_vence_em_e_o_dia_no_fuso_de_quem_estuda(client, db_session):
    """Vence às 22h de hoje em São Paulo = 01h de amanhã em UTC. Pra quem
    está em São Paulo, é hoje."""
    auth, user = _login(client, db_session, "vence_em_fuso@estalo.dev")
    deck = DeckFactory(owner=user)
    c = CardFactory(deck=deck)
    h = _hoje_sp()
    ReviewFactory(user=user, card=c, repetitions=2,
                  due_date=datetime(h.year, h.month, h.day, 22, 0) + timedelta(hours=3))
    db_session.commit()

    assert _vence_em(client, auth, deck.id)[c.id] == h.isoformat()


def test_vence_em_e_por_usuario(client, db_session):
    """O deck é de um usuário só, mas a Review é por usuário: a data não
    pode vir da revisão de outra pessoa."""
    auth, user = _login(client, db_session, "vence_em_dono@estalo.dev")
    _, outro = _login(client, db_session, "vence_em_outro@estalo.dev")
    deck = DeckFactory(owner=user)
    c = CardFactory(deck=deck)
    ReviewFactory(user=outro, card=c, repetitions=2, due_date=datetime.utcnow())
    db_session.commit()

    assert _vence_em(client, auth, deck.id)[c.id] is None
