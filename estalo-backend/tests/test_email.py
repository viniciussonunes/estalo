"""
Forma e caixa do email — a chave da conta.

Dois buracos que isto fecha:

1. A API aceitava qualquer string. O `type="email"` do navegador segurava
   no formulário, mas quem chamasse a API direto criava conta com
   "fulano". Sem recuperação de senha, um email inválido é uma conta que
   ninguém recupera.
2. Maiúscula criava conta inacessível: quem se cadastrava como
   "Vini@x.com" e depois digitava "vini@x.com" no login não entrava. A
   senha estava certa, e não havia como descobrir o problema.
"""
import pytest

from app.models import User
from app.services import email_policy

SENHA = "senha-boa-2026"


def _cadastrar(client, email, senha=SENHA):
    return client.post("/auth/register", json={"email": email, "password": senha})


def _entrar(client, email, senha=SENHA):
    return client.post("/auth/login", data={"username": email, "password": senha})


# ------------------------------------------------------- a regra, isolada

@pytest.mark.parametrize("email", ["fulano", "fulano@", "@dominio.com", "a b@x.com", "fulano@dominio", ""])
def test_email_sem_forma_de_email_e_recusado(email):
    with pytest.raises(email_policy.EmailInvalido):
        email_policy.validar(email)


@pytest.mark.parametrize("email", [
    "vini@estalo.dev",
    "vini.nunes+estudo@sub.dominio.com.br",
    "v@x.io",
])
def test_endereco_normal_passa(email):
    # A validação é frouxa de propósito: rejeitar email válido no cadastro
    # é pior que aceitar um esquisito.
    email_policy.validar(email)


def test_normalizar_tira_espaco_e_baixa_a_caixa():
    assert email_policy.normalizar("  Vini@Estalo.DEV ") == "vini@estalo.dev"


# --------------------------------------------------------------- cadastro

def test_cadastro_recusa_email_torto_com_frase_legivel(client):
    r = _cadastrar(client, "fulano")
    assert r.status_code == 400
    # 400 com detail string, não o 422 do Pydantic (cujo detail é lista de
    # objetos e chegaria na tela como "[object Object]").
    assert isinstance(r.json()["detail"], str)
    assert "não parece válido" in r.json()["detail"]


def test_cadastro_guarda_o_email_normalizado(client, db_session):
    assert _cadastrar(client, "  Vini@Estalo.DEV  ").status_code == 201
    assert db_session.query(User).first().email == "vini@estalo.dev"


def test_nao_da_pra_criar_a_mesma_conta_trocando_a_caixa(client):
    assert _cadastrar(client, "vini@estalo.dev").status_code == 201
    r = _cadastrar(client, "VINI@estalo.dev")
    assert r.status_code == 400
    assert "já está cadastrado" in r.json()["detail"]


# ------------------------------------------------------------------ login

def test_entra_digitando_com_outra_caixa(client):
    # O caso que trancava gente fora da própria conta.
    _cadastrar(client, "vini@estalo.dev")
    assert _entrar(client, "Vini@Estalo.DEV").status_code == 200


def test_espaco_sobrando_nao_impede_o_login(client):
    # Teclado de celular adora um espaço no fim.
    _cadastrar(client, "vini@estalo.dev")
    assert _entrar(client, " vini@estalo.dev ").status_code == 200


def test_conta_antiga_gravada_com_maiuscula_continua_entrando(client, db_session):
    """Contas criadas ANTES da normalização têm a caixa original no banco.

    A comparação baixa a caixa dos DOIS lados, então elas continuam
    entrando -- inclusive digitando de um jeito diferente do cadastro.
    Sem isso, a correção teria trancado justamente quem já estava preso.
    """
    from app.core.security import hash_password
    db_session.add(User(email="Antigo@Estalo.DEV", hashed_password=hash_password(SENHA)))
    db_session.commit()

    assert _entrar(client, "antigo@estalo.dev").status_code == 200
    assert _entrar(client, "Antigo@Estalo.DEV").status_code == 200


def test_email_inexistente_continua_401(client):
    assert _entrar(client, "ninguem@estalo.dev").status_code == 401
