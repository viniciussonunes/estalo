"""
Freio de força bruta no login.

O que estava valendo antes: `/auth/login` aceitava tentativas ilimitadas.
Com o cadastro aceitando qualquer senha (inclusive de um caractere) e sem
troca de senha no app, adivinhar a senha de uma conta era rodar um laço.

Estes testes prendem as duas metades: a escada de bloqueio (a regra, em
services/login_throttle.py) e o endpoint (429, Retry-After, e o fato de
acertar zerar tudo).
"""
from datetime import timedelta

import pytest

from app.services import login_throttle
from app.services.login_throttle import (
    ERROS_ATE_BLOQUEAR,
    agora_utc,
    mensagem_de_bloqueio,
    registrar_falha,
    registrar_sucesso,
    segundos_de_bloqueio,
)


class UsuarioFalso:
    """Só as duas colunas que o freio usa -- não precisa de banco pra
    testar a regra."""
    def __init__(self):
        self.failed_login_count = 0
        self.locked_until = None


# ------------------------------------------------------------ a regra

def test_erros_abaixo_do_limite_nao_bloqueiam():
    u = UsuarioFalso()
    for _ in range(ERROS_ATE_BLOQUEAR - 1):
        assert registrar_falha(u) == 0
    assert segundos_de_bloqueio(u) == 0


def test_o_bloqueio_sobe_em_escada_e_para_no_teto():
    u = UsuarioFalso()
    duracoes = []
    # Três rodadas de erros: cada rodada completa deve subir um degrau.
    for _ in range(4 * ERROS_ATE_BLOQUEAR):
        resultado = registrar_falha(u)
        if resultado:
            duracoes.append(resultado)

    assert duracoes[:3] == [60, 5 * 60, 15 * 60]
    # Da quarta rodada em diante fica no teto -- não cresce pra sempre.
    assert duracoes[3] == 15 * 60


def test_acertar_a_senha_zera_a_sequencia():
    u = UsuarioFalso()
    for _ in range(ERROS_ATE_BLOQUEAR):
        registrar_falha(u)
    assert segundos_de_bloqueio(u) > 0

    registrar_sucesso(u)
    assert u.failed_login_count == 0
    assert segundos_de_bloqueio(u) == 0


def test_o_bloqueio_expira_sozinho():
    u = UsuarioFalso()
    for _ in range(ERROS_ATE_BLOQUEAR):
        registrar_falha(u)
    depois = agora_utc() + timedelta(minutes=2)
    assert segundos_de_bloqueio(u, agora=depois) == 0


def test_a_mensagem_fala_em_minutos_nao_em_segundos():
    # "tente de novo em 847 segundos" não ajuda ninguém.
    assert "1 minuto" in mensagem_de_bloqueio(45)
    assert "5 minutos" in mensagem_de_bloqueio(5 * 60)
    assert "segundos" not in mensagem_de_bloqueio(15 * 60)


# ---------------------------------------------------------- o endpoint

CREDENCIAIS = {"email": "alvo@estalo.dev", "password": "senha-de-verdade"}


def _cadastrar(client):
    r = client.post("/auth/register", json=CREDENCIAIS)
    assert r.status_code == 201


def _tentar(client, senha):
    return client.post(
        "/auth/login",
        data={"username": CREDENCIAIS["email"], "password": senha},
    )


def test_endpoint_bloqueia_depois_de_erros_seguidos(client):
    _cadastrar(client)

    for _ in range(ERROS_ATE_BLOQUEAR - 1):
        assert _tentar(client, "chute").status_code == 401

    bloqueou = _tentar(client, "chute")
    assert bloqueou.status_code == 429
    # Retry-After é o que diz ao cliente (e a qualquer proxy) quando voltar.
    assert int(bloqueou.headers["Retry-After"]) > 0
    assert "tentativas" in bloqueou.json()["detail"].lower()


def test_bloqueada_a_conta_nem_a_senha_certa_entra(client):
    _cadastrar(client)
    for _ in range(ERROS_ATE_BLOQUEAR):
        _tentar(client, "chute")

    # A senha correta também bate na porta fechada. É o ponto do freio:
    # se a senha certa passasse, um atacante entraria no instante em que
    # acertasse, e o bloqueio não teria segurado nada.
    r = _tentar(client, CREDENCIAIS["password"])
    assert r.status_code == 429


def test_acertar_antes_do_limite_limpa_o_contador(client):
    _cadastrar(client)
    for _ in range(ERROS_ATE_BLOQUEAR - 1):
        _tentar(client, "chute")

    assert _tentar(client, CREDENCIAIS["password"]).status_code == 200

    # Zerado: dá pra errar de novo o mesmo tanto sem bloquear. Sem isso,
    # erros espalhados por semanas se somariam e trancariam alguém que
    # nunca foi atacado.
    for _ in range(ERROS_ATE_BLOQUEAR - 1):
        assert _tentar(client, "chute").status_code == 401


def test_email_inexistente_continua_respondendo_401(client):
    # Não há linha pra contar, e não há o que proteger. O importante é não
    # explodir nem devolver 500.
    r = client.post(
        "/auth/login",
        data={"username": "ninguem@estalo.dev", "password": "x"},
    )
    assert r.status_code == 401


def test_login_normal_nao_regrediu(client):
    _cadastrar(client)
    r = _tentar(client, CREDENCIAIS["password"])
    assert r.status_code == 200
    assert r.json()["access_token"]
