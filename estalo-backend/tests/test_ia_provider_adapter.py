"""
Testes do Adaptador de provedor de IA (_chamar_ia, em
error_explanation_service.py) — confirma que trocar IA_PROVIDER
("gemini" | "openai") muda só QUAL API é chamada, sem alterar quota,
formato de entrada/saída, nem exigir a chave do provedor inativo.
"""
from unittest.mock import Mock, patch

import pytest

from app.core.config import settings
from app.services.ai import IAError, QuotaExceededError
from app.services.error_explanation_service import (
    OPENAI_MODEL, _chamar_ia, explicar_erro,
)
from tests.factories import CardFactory, UserFactory


def _resposta_gemini_mock(texto="resposta do gemini"):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": texto}]}}]}
    resp.raise_for_status.return_value = None
    return resp


def _resposta_openai_mock(texto="resposta da openai"):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": texto}}]}
    resp.raise_for_status.return_value = None
    return resp


def test_adapter_usa_gemini_por_padrao(db_session):
    """IA_PROVIDER default é "gemini" -- não precisa setar nada pra manter
    o comportamento de sempre.

    Mocka _chamar_gemini_raw/_chamar_openai_raw diretamente (não
    httpx.post): "app.services.ai.httpx" e
    "app.services.error_explanation_service.httpx" são o MESMO objeto de
    módulo (import cacheado em sys.modules), então patchear os dois
    "...httpx.post" ao mesmo tempo não cria dois mocks independentes --
    o patch aplicado por último vence e mascara o primeiro pro bloco
    `with` inteiro. Mockar as funções _chamar_<provedor>_raw evita essa
    pegadinha, já que são atributos distintos no namespace de
    error_explanation_service."""
    user = UserFactory()
    assert settings.IA_PROVIDER == "gemini"

    with patch("app.services.error_explanation_service._chamar_gemini_raw", return_value="v1") as mock_gemini, \
         patch("app.services.error_explanation_service._chamar_openai_raw") as mock_openai:
        texto = _chamar_ia("prompt de teste", user.id, db_session, instrucao_sistema="persona")

    assert texto == "v1"
    assert mock_gemini.called
    assert not mock_openai.called


def test_adapter_troca_pra_openai_via_settings(db_session):
    """Mesma função (_chamar_ia), mesma entrada/saída -- só
    IA_PROVIDER muda, e o Gemini nem é tocado.

    Aqui sim dá pra usar httpx.post (só UM alvo, sem o conflito descrito
    acima) porque também precisamos inspecionar o payload/headers reais
    da chamada HTTP -- _chamar_gemini_raw é mockado à parte, como função,
    pra confirmar que não foi tocado."""
    user = UserFactory()

    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-fake"), \
         patch("app.services.error_explanation_service.httpx.post", return_value=_resposta_openai_mock("v2")) as mock_openai, \
         patch("app.services.error_explanation_service._chamar_gemini_raw") as mock_gemini:
        texto = _chamar_ia("prompt de teste", user.id, db_session, instrucao_sistema="persona")

    assert texto == "v2"
    assert mock_openai.called
    assert not mock_gemini.called

    # Confere o formato real da requisição -- modelo certo, persona como
    # mensagem "system" separada do conteúdo (mesma separação persona/
    # conteúdo do Gemini, só que no formato de mensagens da OpenAI).
    _, kwargs = mock_openai.call_args
    payload = kwargs["json"]
    assert payload["model"] == OPENAI_MODEL
    assert payload["messages"][0] == {"role": "system", "content": "persona"}
    assert payload["messages"][1] == {"role": "user", "content": "prompt de teste"}
    assert kwargs["headers"]["Authorization"] == "Bearer sk-fake"


def test_openai_sem_chave_configurada_da_erro_claro(db_session):
    user = UserFactory()
    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", ""):
        with pytest.raises(IAError, match="OpenAI"):
            _chamar_ia("prompt", user.id, db_session)


def test_gemini_ativo_nao_exige_openai_key(db_session):
    """OPENAI_API_KEY vazia não deve travar NADA enquanto o provedor
    ativo continua sendo o Gemini -- só é lida/validada quando
    IA_PROVIDER=openai de fato."""
    user = UserFactory()
    with patch.object(settings, "IA_PROVIDER", "gemini"), \
         patch.object(settings, "OPENAI_API_KEY", ""), \
         patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("ok")):
        texto = _chamar_ia("prompt", user.id, db_session)
    assert texto == "ok"


def test_provider_desconhecido_da_erro_claro(db_session):
    user = UserFactory()
    with patch.object(settings, "IA_PROVIDER", "claude"):
        with pytest.raises(IAError, match="IA_PROVIDER"):
            _chamar_ia("prompt", user.id, db_session)


def test_quota_bloqueia_independente_do_provedor(db_session):
    """O Quota Manager não pode virar um "furo" só porque o provedor
    mudou -- o quota-check acontece ANTES de escolher pra qual API
    despachar, então bloqueia os dois igual."""
    from datetime import date
    from app.models.user_quota import UserQuota

    user = UserFactory()
    db_session.add(UserQuota(user_id=user.id, daily_tokens_consumed=50_000, daily_limit=50_000, last_reset_date=date.today()))
    db_session.commit()

    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-fake"), \
         patch("app.services.error_explanation_service.httpx.post") as mock_openai:
        with pytest.raises(QuotaExceededError):
            _chamar_ia("prompt", user.id, db_session)

    assert not mock_openai.called


def test_explicar_erro_ponta_a_ponta_com_openai(db_session):
    """Prova que o adaptador está de fato plugado em explicar_erro (não
    só testável isoladamente) -- roda o fluxo real de Miss com
    IA_PROVIDER=openai."""
    user = UserFactory()
    card = CardFactory()

    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-fake"), \
         patch("app.services.error_explanation_service.httpx.post", return_value=_resposta_openai_mock("explicação via openai")):
        resultado = explicar_erro(card.id, "Pergunta?", "Certa", "Errada", user.id, db_session)

    assert resultado.explanation == "explicação via openai"
    assert resultado.versao == 1
