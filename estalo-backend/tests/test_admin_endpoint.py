"""
Testes dos endpoints administrativos (/admin/users, PATCH .../limit).

Foco principal: autorização. O pedido original só dizia "protegido por
autenticação" -- estes testes provam por que isso não bastaria (qualquer
usuário logado veria/alteraria a cota de todo mundo) e que require_admin
(app/dependencies.py) de fato bloqueia quem não está em ADMIN_EMAILS.
"""
from unittest.mock import patch

from app.core.config import settings
from app.models.user_quota import DEFAULT_DAILY_LIMIT


def _registrar_e_logar(client, email, senha="senha123"):
    client.post("/auth/register", json={"email": email, "password": senha})
    login = client.post("/auth/login", data={"username": email, "password": senha})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_usuario_comum_recebe_403_em_listar_usuarios(client):
    auth = _registrar_e_logar(client, "comum@estalo.dev")
    with patch.object(settings, "ADMIN_EMAILS", "outro-admin@estalo.dev"):
        resp = client.get("/admin/users", headers=auth)
    assert resp.status_code == 403


def test_usuario_comum_recebe_403_em_atualizar_limite(client):
    auth = _registrar_e_logar(client, "comum2@estalo.dev")
    with patch.object(settings, "ADMIN_EMAILS", "outro-admin@estalo.dev"):
        resp = client.patch("/admin/users/1/limit", json={"daily_limit": 1000}, headers=auth)
    assert resp.status_code == 403


def test_sem_admin_emails_configurado_ninguem_entra(client):
    """Vazio por padrão -- nem o próprio dono do app entra sem configurar
    ADMIN_EMAILS explicitamente (não existe 'admin de fábrica')."""
    auth = _registrar_e_logar(client, "dono@estalo.dev")
    with patch.object(settings, "ADMIN_EMAILS", ""):
        resp = client.get("/admin/users", headers=auth)
    assert resp.status_code == 403


def test_admin_lista_usuarios_com_defaults_sem_linha_de_cota(client):
    """Usuário que nunca chamou IA ainda não tem linha em user_quotas --
    deve aparecer na listagem mesmo assim, com os defaults."""
    _registrar_e_logar(client, "sememquota@estalo.dev")
    admin_auth = _registrar_e_logar(client, "admin@estalo.dev")

    with patch.object(settings, "ADMIN_EMAILS", "admin@estalo.dev"):
        resp = client.get("/admin/users", headers=admin_auth)

    assert resp.status_code == 200
    corpo = resp.json()
    emails = {u["email"] for u in corpo}
    assert "sememquota@estalo.dev" in emails
    assert "admin@estalo.dev" in emails
    alvo = next(u for u in corpo if u["email"] == "sememquota@estalo.dev")
    assert alvo["daily_tokens_consumed"] == 0
    assert alvo["daily_limit"] == DEFAULT_DAILY_LIMIT


def test_admin_atualiza_limite_de_outro_usuario(client):
    user_auth = _registrar_e_logar(client, "alvo@estalo.dev")
    admin_auth = _registrar_e_logar(client, "admin2@estalo.dev")

    # descobre o user_id do alvo via /admin/users (não há /auth/me com id direto no schema testado aqui)
    with patch.object(settings, "ADMIN_EMAILS", "admin2@estalo.dev"):
        lista = client.get("/admin/users", headers=admin_auth).json()
        alvo_id = next(u["user_id"] for u in lista if u["email"] == "alvo@estalo.dev")

        resp = client.patch(f"/admin/users/{alvo_id}/limit", json={"daily_limit": 500}, headers=admin_auth)

    assert resp.status_code == 200
    assert resp.json()["daily_limit"] == 500
    assert resp.json()["email"] == "alvo@estalo.dev"


def test_atualizar_limite_de_usuario_inexistente_da_404(client):
    admin_auth = _registrar_e_logar(client, "admin3@estalo.dev")
    with patch.object(settings, "ADMIN_EMAILS", "admin3@estalo.dev"):
        resp = client.patch("/admin/users/999999/limit", json={"daily_limit": 500}, headers=admin_auth)
    assert resp.status_code == 404


def test_limite_negativo_e_rejeitado_pela_validacao(client):
    admin_auth = _registrar_e_logar(client, "admin4@estalo.dev")
    with patch.object(settings, "ADMIN_EMAILS", "admin4@estalo.dev"):
        resp = client.patch("/admin/users/1/limit", json={"daily_limit": -10}, headers=admin_auth)
    assert resp.status_code == 422
