"""
Testes do Adaptador de provedor de IA (_chamar_ia, em app/services/ai.py)
— confirma que trocar IA_PROVIDER ("gemini" | "openai") muda só QUAL API é
chamada, sem alterar quota, formato de entrada/saída, nem exigir a chave
do provedor inativo. Cobre também os pontos de entrada que passaram a
usar o adaptador: error_explanation_service.explicar_erro, tutor_service.
explicar_card e ai.gerar_cards_completos -- provando que a troca de
IA_PROVIDER é global pra plataforma, não só pro Tutor de erro.
"""
from unittest.mock import Mock, patch

import httpx
import pytest
from openai import APIConnectionError, AuthenticationError

from app.core.config import settings
from app.services.ai import OPENAI_MODEL, IAError, QuotaExceededError, _chamar_ia
from app.services.error_explanation_service import explicar_erro
from app.services.tutor_service import explicar_card
from tests.factories import CardFactory, UserFactory


def _resposta_gemini_mock(texto="resposta do gemini"):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": texto}]}}]}
    resp.raise_for_status.return_value = None
    return resp


def _cliente_openai_mock(texto="resposta da openai"):
    """Mock do client oficial `openai.OpenAI` -- resposta com o mesmo
    shape de cliente.chat.completions.create(...)."""
    resposta = Mock()
    resposta.choices = [Mock(message=Mock(content=texto))]
    cliente = Mock()
    cliente.chat.completions.create.return_value = resposta
    return cliente


def test_adapter_usa_gemini_por_padrao(db_session):
    """IA_PROVIDER default é "gemini" -- não precisa setar nada pra manter
    o comportamento de sempre.

    Mocka _chamar_gemini_raw/_chamar_openai_raw diretamente (não
    httpx.post): patchear "httpx.post" ao mesmo tempo por dois caminhos
    diferentes que resolvem pro MESMO módulo `httpx` cacheado não cria
    dois mocks independentes -- o patch aplicado por último vence e
    mascara o primeiro pro bloco `with` inteiro. Mockar as funções
    _chamar_<provedor>_raw evita essa pegadinha, já que são atributos
    distintos no namespace de app.services.ai."""
    user = UserFactory()
    assert settings.IA_PROVIDER == "gemini"

    with patch("app.services.ai._chamar_gemini_raw", return_value="v1") as mock_gemini, \
         patch("app.services.ai._chamar_openai_raw") as mock_openai:
        texto = _chamar_ia("prompt de teste", user.id, db_session, instrucao_sistema="persona")

    assert texto == "v1"
    assert mock_gemini.called
    assert not mock_openai.called


def test_adapter_troca_pra_openai_via_settings(db_session):
    """Mesma função (_chamar_ia), mesma entrada/saída -- só
    IA_PROVIDER muda, e o Gemini nem é tocado.

    Mocka a classe OpenAI (biblioteca oficial) em vez de httpx.post,
    já que _chamar_openai_raw agora fala com a API via `openai.OpenAI`,
    não HTTP cru -- inspeciona o payload real (model/messages) passado
    pra client.chat.completions.create(...)."""
    user = UserFactory()
    cliente_mock = _cliente_openai_mock("v2")

    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-fake"), \
         patch("app.services.ai.OpenAI", return_value=cliente_mock) as mock_cls, \
         patch("app.services.ai._chamar_gemini_raw") as mock_gemini:
        texto = _chamar_ia("prompt de teste", user.id, db_session, instrucao_sistema="persona")

    assert texto == "v2"
    assert cliente_mock.chat.completions.create.called
    assert not mock_gemini.called

    # Confere o formato real da requisição -- modelo certo, persona como
    # mensagem "system" separada do conteúdo (mesma separação persona/
    # conteúdo do Gemini, só que no formato de mensagens da OpenAI).
    _, kwargs = cliente_mock.chat.completions.create.call_args
    assert kwargs["model"] == OPENAI_MODEL
    assert kwargs["messages"][0] == {"role": "system", "content": "persona"}
    assert kwargs["messages"][1] == {"role": "user", "content": "prompt de teste"}

    # Confere que o client foi construído com a chave certa.
    _, client_kwargs = mock_cls.call_args
    assert client_kwargs["api_key"] == "sk-fake"


def test_adapter_respeita_override_de_model_so_no_gemini(db_session):
    """`model=` (ex: TUTOR_MODEL usado por tutor_service/
    error_explanation_service) sobrepõe o modelo padrão só no Gemini -- a
    OpenAI usa sempre OPENAI_MODEL, sem variação por serviço."""
    user = UserFactory()

    with patch("app.services.ai._chamar_gemini_raw", return_value="ok") as mock_gemini:
        _chamar_ia("prompt", user.id, db_session, model="gemini-2.5-flash-lite")

    _, kwargs = mock_gemini.call_args
    assert kwargs["model"] == "gemini-2.5-flash-lite"


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
         patch("app.services.ai._chamar_openai_raw") as mock_openai:
        with pytest.raises(QuotaExceededError):
            _chamar_ia("prompt", user.id, db_session)

    assert not mock_openai.called


def test_explicar_erro_ponta_a_ponta_com_openai(db_session):
    """Prova que o adaptador está de fato plugado em explicar_erro (não
    só testável isoladamente) -- roda o fluxo real de Miss com
    IA_PROVIDER=openai."""
    user = UserFactory()
    card = CardFactory()
    cliente_mock = _cliente_openai_mock("explicação via openai")

    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-fake"), \
         patch("app.services.ai.OpenAI", return_value=cliente_mock):
        resultado = explicar_erro(card.id, "Pergunta?", "Certa", "Errada", user.id, db_session)

    assert resultado.explanation == "explicação via openai"
    assert resultado.versao == 1


def test_explicar_card_ponta_a_ponta_com_openai(db_session):
    """tutor_service.explicar_card (Tutor geral, não o de erro) também
    passou a usar o adaptador -- essa é a prova de que IA_PROVIDER na
    Vercel troca a plataforma inteira, não só o Tutor de erro."""
    user = UserFactory()
    cliente_mock = _cliente_openai_mock("explicação do tutor geral via openai")

    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-fake"), \
         patch("app.services.ai.OpenAI", return_value=cliente_mock):
        resultado = explicar_card("Front do card", "Back do card", user.id, db_session)

    assert resultado == "explicação do tutor geral via openai"


def test_gerar_cards_completos_ponta_a_ponta_com_openai(db_session):
    """ai.gerar_cards_completos (geração de cards/quiz) também passou a
    usar o adaptador -- confirma que o parsing de JSON continua
    funcionando igual, independente do provedor por trás."""
    from app.services.ai import gerar_cards_completos

    user = UserFactory()
    bruto = (
        '[{"front":"P1","back":"R1","distractors":["d1","d2","d3"],'
        '"explanation":"exp1"}]'
    )
    cliente_mock = _cliente_openai_mock(bruto)

    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-fake"), \
         patch("app.services.ai.OpenAI", return_value=cliente_mock):
        cards = gerar_cards_completos("texto de estudo", 1, user.id, db_session)

    assert cards == [{
        "front": "P1", "back": "R1",
        "distractors": ["d1", "d2", "d3"], "explanation": "exp1",
    }]


def test_erro_nao_retryable_da_openai_e_capturado_pelo_sentry(db_session):
    """Chave inválida, saldo/cota esgotados etc. -- os routers sempre
    convertem IAError num 503/429 genérico pro usuário, então sem
    captura explícita aqui o Sentry NUNCA veria o erro real da OpenAI.
    Cobre o pedido explícito: "caso o saldo acabe ou a API falhe, o
    Sentry capture o erro corretamente"."""
    user = UserFactory()
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(401, request=request, json={"error": {"message": "saldo esgotado"}})
    erro = AuthenticationError("saldo esgotado", response=response, body=None)

    cliente_mock = Mock()
    cliente_mock.chat.completions.create.side_effect = erro

    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-fake"), \
         patch("app.services.ai.OpenAI", return_value=cliente_mock), \
         patch("app.services.ai.sentry_sdk.capture_exception") as mock_capture:
        with pytest.raises(IAError):
            _chamar_ia("prompt", user.id, db_session)

    mock_capture.assert_called_once_with(erro)
    # Erro não-retryable: só UMA tentativa, não duas.
    assert cliente_mock.chat.completions.create.call_count == 1


def test_erro_retryable_da_openai_tenta_de_novo_e_captura_no_sentry(db_session):
    """Falha de conexão/timeout/rate-limit vale uma 2ª tentativa -- mas
    cada tentativa que falhar ainda precisa ir pro Sentry."""
    user = UserFactory()
    erro = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))

    cliente_mock = Mock()
    cliente_mock.chat.completions.create.side_effect = erro

    with patch.object(settings, "IA_PROVIDER", "openai"), \
         patch.object(settings, "OPENAI_API_KEY", "sk-fake"), \
         patch("app.services.ai.OpenAI", return_value=cliente_mock), \
         patch("app.services.ai.sentry_sdk.capture_exception") as mock_capture, \
         patch("app.services.ai.time.sleep"):
        with pytest.raises(IAError, match="2 tentativas"):
            _chamar_ia("prompt", user.id, db_session)

    assert cliente_mock.chat.completions.create.call_count == 2
    assert mock_capture.call_count == 2
