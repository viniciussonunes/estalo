"""
Testes das capacidades novas de tutor_service.py (evolução do modo de
aprendizado assistido, ver app/services/tutor_service.py e
routers/cards.py):

1. explicar_conceito_breve() + POST /cards/{id}/tutor?action=explain
   (botão "Explicar" do Modo Revelar) -- resposta curta, sem cache,
   endpoint separado do Tutor Inteligente completo
   (POST /study/cards/{id}/tutor).
2. analisar_feedback() + POST /cards/{id}/tutor?action=analyze (botão
   "Errei" do Modo Estudo -- Mentoria Ativa) -- classificação de erro
   (omissão/imprecisão/erro conceitual) + gap cognitivo + explicação,
   tudo numa chamada de IA só. Testado tanto direto na função de serviço
   quanto via HTTP (validação de user_attempt obrigatório, telemetria,
   isolamento entre usuários).

Gemini mockado, sem rede (mesma técnica do resto da suíte: httpx, não
`requests`, mock entra em app.services.ai.httpx.post).
"""
import json
from unittest.mock import Mock, patch

import pytest

from app.core.config import settings
from app.services.ai import IAError
from app.services.tutor_service import AnaliseFeedback, analisar_feedback, explicar_conceito_breve


def _autenticar(client, email="tutor_analise@estalo.dev"):
    client.post("/auth/register", json={"email": email, "password": "senha123"})
    login = client.post("/auth/login", data={"username": email, "password": "senha123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _criar_card(client, auth, front="Qual é a capital da França?", back="Paris"):
    deck = client.post("/decks", json={"title": "Deck Análise"}, headers=auth).json()
    card = client.post(f"/decks/{deck['id']}/cards", json={"front": front, "back": back}, headers=auth).json()
    return card


def _resposta_gemini_mock(texto: str):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": texto}]}}]}
    resp.raise_for_status.return_value = None
    return resp


# --- POST /cards/{id}/tutor (botão "Explicar") ----------------------------

def test_explicar_endpoint_retorna_explicacao_curta(client):
    auth = _autenticar(client)
    card = _criar_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("Paris é a capital desde o século 12.")) as mock_post:
        resp = client.post(f"/cards/{card['id']}/tutor", headers=auth)

    assert resp.status_code == 200
    assert resp.json()["explanation"] == "Paris é a capital desde o século 12."
    assert mock_post.called


def test_explicar_endpoint_nao_usa_cache_chama_ia_de_novo(client):
    """Diferente do Tutor Inteligente completo (que cacheia em
    Card.tutor_explanation), o botão "Explicar" é deliberadamente sem
    cache -- duas chamadas seguidas batem no Gemini as duas vezes."""
    auth = _autenticar(client, "sem_cache@estalo.dev")
    card = _criar_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("Explicação 1")) as mock_post:
        client.post(f"/cards/{card['id']}/tutor", headers=auth)
        client.post(f"/cards/{card['id']}/tutor", headers=auth)

    assert mock_post.call_count == 2


def test_explicar_endpoint_action_invalida_da_400_sem_chamar_ia(client):
    auth = _autenticar(client, "action_invalida@estalo.dev")
    card = _criar_card(client, auth)

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(f"/cards/{card['id']}/tutor?action=analyze", headers=auth)

    assert resp.status_code == 400
    assert not mock_post.called


def test_explicar_endpoint_erro_da_ia_retorna_503(client):
    auth = _autenticar(client, "erro_ia@estalo.dev")
    card = _criar_card(client, auth)

    resp_erro = Mock()
    resp_erro.status_code = 503
    resp_erro.raise_for_status.side_effect = Exception("indisponível")

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=resp_erro):
        resp = client.post(f"/cards/{card['id']}/tutor", headers=auth)

    assert resp.status_code == 503


def test_explicar_endpoint_card_de_outro_usuario_da_404(client):
    dono_auth = _autenticar(client, "dono_explicar@estalo.dev")
    card = _criar_card(client, dono_auth)

    intruso_auth = _autenticar(client, "intruso_explicar@estalo.dev")

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(f"/cards/{card['id']}/tutor", headers=intruso_auth)

    assert resp.status_code == 404
    assert not mock_post.called


def test_explicar_conceito_breve_prompt_pede_no_maximo_3_frases_e_sem_markdown(client):
    auth = _autenticar(client, "prompt_breve@estalo.dev")
    card = _criar_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("ok")) as mock_post:
        client.post(f"/cards/{card['id']}/tutor", headers=auth)

    prompt_sistema = mock_post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
    assert "3 frases" in prompt_sistema
    assert "sem markdown" in prompt_sistema.lower() or "nunca use **" in prompt_sistema.lower()


# --- POST /cards/{id}/tutor?action=analyze (Mentoria Ativa, botão "Errei") -

_ANALISE_OMISSAO = json.dumps({
    "tipo_erro": "omissao",
    "gap_cognitivo": "Aluno esqueceu de mencionar o ano da revolução.",
    "explicacao": "Faltou o ano -- 1789. O resto da resposta está correto.",
})


def test_analyze_endpoint_retorna_classificacao_completa(client):
    auth = _autenticar(client, "analyze_ok@estalo.dev")
    card = _criar_card(client, auth, front="Quando começou a Revolução Francesa?", back="1789")

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_ANALISE_OMISSAO)) as mock_post:
        resp = client.post(
            "/cards/%d/tutor?action=analyze" % card["id"],
            json={"user_attempt": "Foi uma revolta popular"},
            headers=auth,
        )

    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["tipo_erro"] == "omissao"
    assert "ano" in corpo["gap_cognitivo"].lower()
    assert "1789" in corpo["explanation"]
    assert mock_post.called


def test_analyze_endpoint_sem_user_attempt_da_400_sem_chamar_ia(client):
    auth = _autenticar(client, "analyze_sem_tentativa@estalo.dev")
    card = _criar_card(client, auth)

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(f"/cards/{card['id']}/tutor?action=analyze", json={}, headers=auth)

    assert resp.status_code == 400
    assert not mock_post.called


def test_analyze_endpoint_user_attempt_vazio_da_400_sem_chamar_ia(client):
    auth = _autenticar(client, "analyze_tentativa_vazia@estalo.dev")
    card = _criar_card(client, auth)

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(
            f"/cards/{card['id']}/tutor?action=analyze",
            json={"user_attempt": "   "},
            headers=auth,
        )

    assert resp.status_code == 400
    assert not mock_post.called


def test_analyze_endpoint_erro_da_ia_retorna_503(client):
    auth = _autenticar(client, "analyze_erro_ia@estalo.dev")
    card = _criar_card(client, auth)

    resp_erro = Mock()
    resp_erro.status_code = 503
    resp_erro.raise_for_status.side_effect = Exception("indisponível")

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=resp_erro):
        resp = client.post(
            f"/cards/{card['id']}/tutor?action=analyze",
            json={"user_attempt": "não sei"},
            headers=auth,
        )

    assert resp.status_code == 503


def test_analyze_endpoint_card_de_outro_usuario_da_404_sem_chamar_ia(client):
    dono_auth = _autenticar(client, "dono_analyze@estalo.dev")
    card = _criar_card(client, dono_auth)

    intruso_auth = _autenticar(client, "intruso_analyze@estalo.dev")

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(
            f"/cards/{card['id']}/tutor?action=analyze",
            json={"user_attempt": "tentativa"},
            headers=intruso_auth,
        )

    assert resp.status_code == 404
    assert not mock_post.called


def test_analyze_endpoint_telemetria_loga_tipo_erro_sem_vazar_tentativa_do_usuario(client, capsys):
    """Confere o pedido explícito: telemetria registra o tipo de erro e o
    tema (a pergunta do card), NUNCA a tentativa do usuário (texto livre,
    pode conter algo pessoal)."""
    auth = _autenticar(client, "telemetria@estalo.dev")
    card = _criar_card(client, auth, front="Quando começou a Revolução Francesa?", back="1789")

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_ANALISE_OMISSAO)):
        client.post(
            "/cards/%d/tutor?action=analyze" % card["id"],
            json={"user_attempt": "informação pessoal sensível do aluno"},
            headers=auth,
        )

    saida = capsys.readouterr().out
    assert "[feedback_analyzed]" in saida
    assert "tipo_erro=omissao" in saida
    assert "Revolução Francesa" in saida
    assert "informação pessoal sensível" not in saida


def test_analisar_feedback_classifica_e_retorna_dataclass(db_session):
    from tests.factories import UserFactory
    user = UserFactory()

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_ANALISE_OMISSAO)):
        resultado = analisar_feedback(
            "A revolução francesa foi uma revolta popular",
            "A revolução francesa começou em 1789",
            "Quando/como começou a revolução francesa?",
            user.id, db_session,
        )

    assert isinstance(resultado, AnaliseFeedback)
    assert resultado.tipo_erro == "omissao"
    assert "ano" in resultado.gap_cognitivo.lower()
    assert "1789" in resultado.explicacao


@pytest.mark.parametrize("tipo", ["omissao", "imprecisao", "erro_conceitual"])
def test_analisar_feedback_aceita_as_3_categorias_validas(db_session, tipo):
    from tests.factories import UserFactory
    user = UserFactory()

    payload = json.dumps({"tipo_erro": tipo, "gap_cognitivo": "gap", "explicacao": "exp"})
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(payload)):
        resultado = analisar_feedback("tentativa", "certa", "contexto", user.id, db_session)

    assert resultado.tipo_erro == tipo


def test_analisar_feedback_tipo_erro_invalido_da_ia_lanca_iaerror(db_session):
    from tests.factories import UserFactory
    user = UserFactory()

    payload = json.dumps({"tipo_erro": "categoria_inventada", "gap_cognitivo": "gap", "explicacao": "exp"})
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(payload)):
        with pytest.raises(IAError, match="tipo inesperado"):
            analisar_feedback("tentativa", "certa", "contexto", user.id, db_session)


def test_analisar_feedback_json_invalido_lanca_iaerror(db_session):
    from tests.factories import UserFactory
    user = UserFactory()

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("isso não é JSON")):
        with pytest.raises(IAError):
            analisar_feedback("tentativa", "certa", "contexto", user.id, db_session)


def test_analisar_feedback_campos_faltando_lanca_iaerror(db_session):
    from tests.factories import UserFactory
    user = UserFactory()

    payload = json.dumps({"tipo_erro": "omissao", "gap_cognitivo": "", "explicacao": ""})
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(payload)):
        with pytest.raises(IAError):
            analisar_feedback("tentativa", "certa", "contexto", user.id, db_session)


def test_analisar_feedback_prompt_pede_tom_ajustado_por_assunto(db_session):
    from tests.factories import UserFactory
    user = UserFactory()

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_ANALISE_OMISSAO)) as mock_post:
        analisar_feedback("tentativa", "certa", "contexto", user.id, db_session)

    prompt_sistema = mock_post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
    assert "pedagógico e encorajador" in prompt_sistema
    assert "técnico e direto" in prompt_sistema
    assert "gap_cognitivo" in prompt_sistema


def test_analisar_feedback_quota_bloqueia_sem_chamar_rede(db_session):
    from datetime import date

    from app.models.user_quota import UserQuota
    from app.services.ai import QuotaExceededError
    from tests.factories import UserFactory

    user = UserFactory()
    db_session.add(UserQuota(user_id=user.id, daily_tokens_consumed=50_000, daily_limit=50_000, last_reset_date=date.today()))
    db_session.commit()

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post") as mock_post:
        with pytest.raises(QuotaExceededError):
            analisar_feedback("tentativa", "certa", "contexto", user.id, db_session)

    assert not mock_post.called
