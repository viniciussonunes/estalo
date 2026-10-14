"""
Tamanho do lote da Revisão Geral, escolhido pelo usuário.

Era 15 fixo no código (`.limit(15)` em global-reviews). Não é um teto de
quanto dá pra estudar -- desde o "Continuar · N restantes", o lote
seguinte vem a um clique -- é o tamanho de uma sentada, e isso varia por
pessoa e por rotina.

Mora na CONTA e não no aparelho porque é preferência de estudo, não de
tela: quem ajusta no celular espera o mesmo número no notebook. (A
Revisão Geral é consulta ao servidor, então guardar local também não
daria ganho offline nenhum.)

A faixa 5-50 não é estética: a Revisão Geral monta a resposta inteira
numa request, e a auto-cura do quiz no Modo Aprender processa 20 cards
por chamada de IA.
"""
from datetime import datetime, timedelta

from app.models.user import (
    CARDS_POR_SESSAO_MAX,
    CARDS_POR_SESSAO_MIN,
    CARDS_POR_SESSAO_PADRAO,
)


def _autenticar(client, email):
    client.post("/auth/register", json={"email": email, "password": "senha-de-teste-2026"})
    login = client.post("/auth/login", data={"username": email, "password": "senha-de-teste-2026"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _deck_com_vencidos(client, auth, quantos):
    """Cria `quantos` cards JÁ estudados e vencidos -- é o que a Revisão
    Geral serve (cards nunca estudados ficam de fora de propósito)."""
    deck = client.post("/decks", json={"title": "Deck grande"}, headers=auth).json()
    ontem = (datetime.utcnow() - timedelta(days=1)).isoformat()
    for i in range(quantos):
        card = client.post(
            f"/decks/{deck['id']}/cards",
            json={"front": f"Pergunta {i}", "back": f"Resposta {i}"}, headers=auth,
        ).json()
        # Responder cria o Review; respondido_em no passado deixa vencido.
        client.post(
            f"/study/cards/{card['id']}/answer",
            json={"quality": 1, "ignorar_elegibilidade": True, "respondido_em": ontem},
            headers=auth,
        )
    return deck


def test_padrao_continua_15_pra_quem_nunca_mexeu(client):
    # Ninguém pode sentir o deploy: 15 era o número fixo de antes.
    auth = _autenticar(client, "sessao_padrao@estalo.dev")
    assert client.get("/auth/me", headers=auth).json()["cards_por_sessao"] == CARDS_POR_SESSAO_PADRAO

    _deck_com_vencidos(client, auth, 20)
    fila = client.get("/study/global-reviews", headers=auth).json()
    assert len(fila) == 15


def test_a_revisao_geral_serve_o_tanto_escolhido(client):
    auth = _autenticar(client, "sessao_escolhida@estalo.dev")
    _deck_com_vencidos(client, auth, 20)

    resp = client.patch("/auth/me/preferencias", json={"cards_por_sessao": 7}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["cards_por_sessao"] == 7  # devolve o UserOut inteiro

    assert len(client.get("/study/global-reviews", headers=auth).json()) == 7


def test_a_escolha_sobrevive_e_aparece_no_me(client):
    # É isso que faz a preferência valer em QUALQUER aparelho: ela vem no
    # /auth/me, que todo cliente chama ao abrir.
    auth = _autenticar(client, "sessao_persiste@estalo.dev")
    client.patch("/auth/me/preferencias", json={"cards_por_sessao": 40}, headers=auth)
    assert client.get("/auth/me", headers=auth).json()["cards_por_sessao"] == 40


def test_fora_da_faixa_e_recusado(client):
    auth = _autenticar(client, "sessao_faixa@estalo.dev")
    for valor in (0, CARDS_POR_SESSAO_MIN - 1, CARDS_POR_SESSAO_MAX + 1, 1000, -5):
        resp = client.patch("/auth/me/preferencias", json={"cards_por_sessao": valor}, headers=auth)
        assert resp.status_code == 422, f"{valor} deveria ser recusado"
    # E nada foi gravado pelo caminho.
    assert client.get("/auth/me", headers=auth).json()["cards_por_sessao"] == CARDS_POR_SESSAO_PADRAO


def test_os_extremos_da_faixa_sao_aceitos(client):
    auth = _autenticar(client, "sessao_extremos@estalo.dev")
    for valor in (CARDS_POR_SESSAO_MIN, CARDS_POR_SESSAO_MAX):
        assert client.patch(
            "/auth/me/preferencias", json={"cards_por_sessao": valor}, headers=auth,
        ).status_code == 200


def test_a_preferencia_e_de_cada_conta(client):
    # Um usuário não pode mexer no tamanho de sessão do outro.
    a = _autenticar(client, "sessao_a@estalo.dev")
    b = _autenticar(client, "sessao_b@estalo.dev")
    client.patch("/auth/me/preferencias", json={"cards_por_sessao": 50}, headers=a)

    assert client.get("/auth/me", headers=a).json()["cards_por_sessao"] == 50
    assert client.get("/auth/me", headers=b).json()["cards_por_sessao"] == CARDS_POR_SESSAO_PADRAO


def test_sem_cracha_nao_muda_nada(client):
    resp = client.patch("/auth/me/preferencias", json={"cards_por_sessao": 30})
    assert resp.status_code == 401
