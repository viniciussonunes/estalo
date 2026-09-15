"""
Comutação de provedor de IA em tempo real.

Motivo: os créditos da OpenAI acabaram e a IA do app inteiro parou -- com
a chave do Gemini configurada e parada. Agora, quando o provedor de
IA_PROVIDER falha, o outro assume NA MESMA chamada (ver _chamar_ia em
app/services/ai.py). Regras que estes testes seguram:

  - a reserva só entra se tiver chave configurada;
  - a reserva só entra se ainda sobrar tempo de função (maxDuration 60s);
  - a reserva faz 1 tentativa, não 2;
  - se os dois falham, o erro cita os dois;
  - cota estourada continua barrando ANTES de qualquer provedor.

Tudo mockado em _chamar_<provedor>_raw, sem rede (mesma técnica de
test_ia_provider_adapter.py).
"""
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import ai
from app.services.ai import IAError, QuotaExceededError, _chamar_ia
from tests.factories import UserFactory


def _com_chaves(provider, gemini="chave-gemini", openai="chave-openai"):
    """Contexto com as duas chaves e o provedor primário escolhido."""
    return (
        patch.object(settings, "IA_PROVIDER", provider),
        patch.object(settings, "GEMINI_API_KEY", gemini),
        patch.object(settings, "OPENAI_API_KEY", openai),
        patch.dict("os.environ", {"OPENAI_API_KEY": openai}),
    )


def _entrar(*ctxs):
    from contextlib import ExitStack
    stack = ExitStack()
    for c in ctxs:
        stack.enter_context(c)
    return stack


def test_openai_falha_e_gemini_assume_na_mesma_chamada(db_session):
    user = UserFactory()
    with _entrar(*_com_chaves("openai")), \
         patch("app.services.ai._chamar_openai_raw", side_effect=IAError("OpenAI respondeu com erro: insufficient_quota")) as openai_raw, \
         patch("app.services.ai._chamar_gemini_raw", return_value="veio do gemini") as gemini_raw:
        texto = _chamar_ia("prompt", user.id, db_session, instrucao_sistema="persona")

    assert texto == "veio do gemini"
    assert openai_raw.call_count == 1
    assert gemini_raw.call_count == 1
    # A reserva entra com 1 tentativa: o primário já gastou as dele.
    assert gemini_raw.call_args.kwargs["tentativas"] == 1
    assert gemini_raw.call_args.kwargs["instrucao_sistema"] == "persona"


def test_gemini_falha_e_openai_assume(db_session):
    user = UserFactory()
    with _entrar(*_com_chaves("gemini")), \
         patch("app.services.ai._chamar_gemini_raw", side_effect=IAError("Gemini indisponível")), \
         patch("app.services.ai._chamar_openai_raw", return_value="veio da openai") as openai_raw:
        texto = _chamar_ia("prompt", user.id, db_session, model="gemini-2.5-flash-lite", desabilitar_thinking=True)

    assert texto == "veio da openai"
    # Conceitos do Gemini não vazam pra OpenAI.
    assert "model" not in openai_raw.call_args.kwargs
    assert "desabilitar_thinking" not in openai_raw.call_args.kwargs


def test_sem_chave_da_reserva_nao_tenta_e_devolve_o_erro_original(db_session):
    user = UserFactory()
    with _entrar(*_com_chaves("gemini", openai="")), \
         patch("app.services.ai._chamar_gemini_raw", side_effect=IAError("Gemini indisponível")), \
         patch("app.services.ai._chamar_openai_raw") as openai_raw:
        with pytest.raises(IAError, match="^Gemini indisponível$"):
            _chamar_ia("prompt", user.id, db_session)
    assert not openai_raw.called


def test_os_dois_falham_e_o_erro_cita_os_dois(db_session):
    user = UserFactory()
    with _entrar(*_com_chaves("openai")), \
         patch("app.services.ai._chamar_openai_raw", side_effect=IAError("OpenAI caiu")), \
         patch("app.services.ai._chamar_gemini_raw", side_effect=IAError("Gemini caiu")):
        with pytest.raises(IAError) as exc:
            _chamar_ia("prompt", user.id, db_session)
    assert "OpenAI caiu" in str(exc.value)
    assert "Gemini caiu" in str(exc.value)


def test_sem_tempo_de_funcao_nao_comuta(db_session):
    # O primário demorou quase o orçamento inteiro (timeouts): começar a
    # reserva agora só estouraria o maxDuration da Vercel com a mesma cara
    # de erro pro usuário. Relógio simulado: 0s ao entrar, 53s ao falhar.
    user = UserFactory()
    with _entrar(*_com_chaves("openai")), \
         patch("app.services.ai.time.monotonic", side_effect=[0.0, ai.ORCAMENTO_S - 2]), \
         patch("app.services.ai._chamar_openai_raw", side_effect=IAError("OpenAI lenta")), \
         patch("app.services.ai._chamar_gemini_raw") as gemini_raw:
        with pytest.raises(IAError, match="OpenAI lenta"):
            _chamar_ia("prompt", user.id, db_session)
    assert not gemini_raw.called


def test_reserva_recebe_so_o_tempo_que_sobrou(db_session):
    # Primário gastou 40s dos 55: a reserva não pode pedir 25s de timeout.
    user = UserFactory()
    with _entrar(*_com_chaves("openai")), \
         patch("app.services.ai.time.monotonic", side_effect=[0.0, 40.0]), \
         patch("app.services.ai._chamar_openai_raw", side_effect=IAError("OpenAI lenta")), \
         patch("app.services.ai._chamar_gemini_raw", return_value="ok") as gemini_raw:
        assert _chamar_ia("prompt", user.id, db_session, timeout=25) == "ok"
    assert gemini_raw.call_args.kwargs["timeout"] == ai.ORCAMENTO_S - 40


def test_cota_estourada_barra_antes_de_qualquer_provedor(db_session):
    user = UserFactory()
    with _entrar(*_com_chaves("openai")), \
         patch("app.services.ai.check_and_consume_tokens", return_value=False), \
         patch("app.services.ai._chamar_openai_raw") as openai_raw, \
         patch("app.services.ai._chamar_gemini_raw") as gemini_raw:
        with pytest.raises(QuotaExceededError):
            _chamar_ia("prompt", user.id, db_session)
    assert not openai_raw.called and not gemini_raw.called


def test_a_comutacao_fica_registrada_no_log(db_session, capsys):
    user = UserFactory()
    with _entrar(*_com_chaves("openai")), \
         patch("app.services.ai._chamar_openai_raw", side_effect=IAError("insufficient_quota")), \
         patch("app.services.ai._chamar_gemini_raw", return_value="ok"):
        _chamar_ia("prompt", user.id, db_session)
    assert "[ia_failover] de=openai para=gemini" in capsys.readouterr().out
