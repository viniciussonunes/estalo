"""
Regra de senha (cadastro) e troca de senha.

O buraco que isso fecha: até 2026-09-13 o cadastro aceitava qualquer senha
-- inclusive "1" -- e NÃO existia endpoint de trocar senha. As duas coisas
juntas: quem entrava com senha fraca ficava com ela pra sempre.
"""
import pytest

from app.services import password_policy
from app.services.login_throttle import ERROS_ATE_BLOQUEAR

CONTA = {"email": "dono@estalo.dev", "password": "senha-boa-2026"}
NOVA = "outra-senha-boa-2026"


def _cadastrar(client, **troca):
    return client.post("/auth/register", json={**CONTA, **troca})


def _entrar(client, senha):
    r = client.post("/auth/login", data={"username": CONTA["email"], "password": senha})
    return r


def _token(client, senha=CONTA["password"]):
    return _entrar(client, senha).json()["access_token"]


def _trocar(client, token, atual, nova):
    return client.post(
        "/auth/change-password",
        json={"senha_atual": atual, "senha_nova": nova},
        headers={"Authorization": f"Bearer {token}"},
    )


# ------------------------------------------------------- a regra, isolada

@pytest.mark.parametrize("senha", ["", "1", "abc", "1234567"])
def test_senha_curta_e_recusada(senha):
    with pytest.raises(password_policy.SenhaFraca):
        password_policy.validar(senha)


def test_senha_obvia_e_recusada_mesmo_tendo_o_tamanho():
    # O ponto de ter lista: "12345678" passa no mínimo de 8 e cai nos
    # primeiros chutes de qualquer ataque.
    with pytest.raises(password_policy.SenhaFraca):
        password_policy.validar("12345678")
    with pytest.raises(password_policy.SenhaFraca):
        password_policy.validar("SENHA123")  # a comparação ignora maiúsculas


def test_senha_nao_pode_ser_o_proprio_email():
    with pytest.raises(password_policy.SenhaFraca):
        password_policy.validar("dono@estalo.dev", email="Dono@Estalo.dev")


def test_senha_longa_demais_e_recusada_em_vez_de_cortada():
    # bcrypt ignora do 72º byte em diante. Cortar calado é pior que
    # recusar: duas senhas diferentes com os mesmos 72 bytes iniciais
    # abririam a mesma conta, e o dono nem saberia.
    with pytest.raises(password_policy.SenhaFraca):
        password_policy.validar("a" * 73)
    # Acento ocupa 2 bytes: 40 acentos = 80 bytes, mesmo com 40 caracteres.
    with pytest.raises(password_policy.SenhaFraca):
        password_policy.validar("á" * 40)


def test_frase_longa_comum_passa():
    # A regra não exige maiúscula/número/símbolo de propósito -- exigir
    # empurra todo mundo pro mesmo "Senha123!".
    password_policy.validar("meu cachorro chama pipoca")


# ------------------------------------------------------------- cadastro

def test_cadastro_recusa_senha_fraca_com_frase_legivel(client):
    r = _cadastrar(client, password="123")
    assert r.status_code == 400
    # 400 com detail string, e não 422 do Pydantic (cujo detail é uma LISTA
    # de objetos e chegaria na tela como "[object Object]").
    assert isinstance(r.json()["detail"], str)
    assert "8 caracteres" in r.json()["detail"]


def test_cadastro_com_senha_boa_continua_funcionando(client):
    assert _cadastrar(client).status_code == 201
    assert _entrar(client, CONTA["password"]).status_code == 200


# --------------------------------------------------------- troca de senha

def test_troca_de_senha_muda_o_login(client):
    _cadastrar(client)
    token = _token(client)

    assert _trocar(client, token, CONTA["password"], NOVA).status_code == 204

    assert _entrar(client, CONTA["password"]).status_code == 401
    assert _entrar(client, NOVA).status_code == 200


def test_troca_exige_a_senha_atual(client):
    _cadastrar(client)
    token = _token(client)

    # Token válido não basta: aparelho esquecido aberto não pode virar
    # posse da conta -- ainda mais sem recuperação de senha no app.
    r = _trocar(client, token, "chute-errado", NOVA)
    assert r.status_code == 400
    assert "atual" in r.json()["detail"].lower()
    assert _entrar(client, CONTA["password"]).status_code == 200


def test_troca_aplica_a_mesma_regra_de_senha(client):
    _cadastrar(client)
    token = _token(client)
    r = _trocar(client, token, CONTA["password"], "123")
    assert r.status_code == 400
    assert "8 caracteres" in r.json()["detail"]


def test_troca_recusa_repetir_a_senha_atual(client):
    _cadastrar(client)
    token = _token(client)
    r = _trocar(client, token, CONTA["password"], CONTA["password"])
    assert r.status_code == 400
    assert "diferente" in r.json()["detail"].lower()


def test_troca_sem_token_e_barrada(client):
    _cadastrar(client)
    r = client.post(
        "/auth/change-password",
        json={"senha_atual": CONTA["password"], "senha_nova": NOVA},
    )
    assert r.status_code == 401


def test_errar_a_senha_atual_tambem_bate_no_freio(client):
    _cadastrar(client)
    token = _token(client)

    for _ in range(ERROS_ATE_BLOQUEAR - 1):
        assert _trocar(client, token, "chute", NOVA).status_code == 400

    # Sem freio aqui, este endpoint seria a porta dos fundos do que o
    # /login fechou: dá pra adivinhar a senha atual do mesmo jeito.
    travou = _trocar(client, token, "chute", NOVA)
    assert travou.status_code == 429
    assert int(travou.headers["Retry-After"]) > 0


def test_trocar_a_senha_limpa_a_sequencia_de_erros(client):
    _cadastrar(client)
    token = _token(client)
    for _ in range(ERROS_ATE_BLOQUEAR - 1):
        _entrar(client, "chute")

    assert _trocar(client, token, CONTA["password"], NOVA).status_code == 204

    # Retomou o controle da conta: o contador zera junto.
    for _ in range(ERROS_ATE_BLOQUEAR - 1):
        assert _entrar(client, "chute").status_code == 401
