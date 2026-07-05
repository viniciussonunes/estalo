"""
Testes do Quota Manager (app/services/quota_service.py + integração em
app/services/ai.py). Cobre: criação automática da cota no primeiro uso,
consumo/bloqueio por limite diário, reset por virada de dia, e o disparo
de QuotaExceededError dentro de _chamar_gemini quando a cota já estourou
(sem sequer tentar a chamada HTTP -- ver assert de que httpx.post nunca
é chamado nesse caso).
"""
from datetime import date, timedelta
from unittest.mock import patch

from app.core.config import settings
from app.models.user_quota import UserQuota
from app.services.ai import QuotaExceededError, _chamar_gemini
from app.services.quota_service import check_and_consume_tokens, reset_quotas_if_needed
from tests.factories import UserFactory


def test_primeira_chamada_cria_a_cota_com_os_defaults(db_session):
    user = UserFactory()
    assert db_session.get(UserQuota, user.id) is None

    ok = check_and_consume_tokens(user.id, 100, db_session)

    assert ok is True
    quota = db_session.get(UserQuota, user.id)
    assert quota is not None
    assert quota.daily_limit == 50_000
    assert quota.daily_tokens_consumed == 100
    assert quota.last_reset_date == date.today()


def test_consumo_acumula_entre_chamadas(db_session):
    user = UserFactory()
    check_and_consume_tokens(user.id, 100, db_session)
    check_and_consume_tokens(user.id, 250, db_session)

    quota = db_session.get(UserQuota, user.id)
    assert quota.daily_tokens_consumed == 350


def test_bloqueia_quando_estouraria_o_limite(db_session):
    user = UserFactory()
    db_session.add(UserQuota(user_id=user.id, daily_tokens_consumed=49_950, daily_limit=50_000))
    db_session.commit()

    ok = check_and_consume_tokens(user.id, 100, db_session)

    assert ok is False
    # Não debita nada quando bloqueia -- outra tentativa menor ainda deve
    # caber na cota que sobrou.
    quota = db_session.get(UserQuota, user.id)
    assert quota.daily_tokens_consumed == 49_950


def test_permite_exatamente_no_limite(db_session):
    user = UserFactory()
    db_session.add(UserQuota(user_id=user.id, daily_tokens_consumed=49_900, daily_limit=50_000))
    db_session.commit()

    assert check_and_consume_tokens(user.id, 100, db_session) is True
    assert db_session.get(UserQuota, user.id).daily_tokens_consumed == 50_000


def test_reset_quotas_if_needed_zera_em_novo_dia(db_session):
    user = UserFactory()
    ontem = date.today() - timedelta(days=1)
    db_session.add(UserQuota(user_id=user.id, daily_tokens_consumed=49_999, daily_limit=50_000, last_reset_date=ontem))
    db_session.commit()

    quota = reset_quotas_if_needed(user.id, db_session)

    assert quota.daily_tokens_consumed == 0
    assert quota.last_reset_date == date.today()


def test_reset_quotas_if_needed_nao_mexe_no_mesmo_dia(db_session):
    user = UserFactory()
    db_session.add(UserQuota(user_id=user.id, daily_tokens_consumed=123, daily_limit=50_000, last_reset_date=date.today()))
    db_session.commit()

    quota = reset_quotas_if_needed(user.id, db_session)

    assert quota.daily_tokens_consumed == 123


def test_cota_estourada_e_reset_permite_consumir_de_novo(db_session):
    """Reproduz o cenário completo: estourou ontem, vira o dia, hoje já
    pode consumir de novo com o contador zerado."""
    user = UserFactory()
    ontem = date.today() - timedelta(days=1)
    db_session.add(UserQuota(user_id=user.id, daily_tokens_consumed=50_000, daily_limit=50_000, last_reset_date=ontem))
    db_session.commit()

    ok = check_and_consume_tokens(user.id, 100, db_session)

    assert ok is True
    assert db_session.get(UserQuota, user.id).daily_tokens_consumed == 100


def test_chamar_gemini_lanca_quota_exceeded_sem_ir_pra_rede(db_session):
    """O ponto central do pedido: se a cota já estourou, _chamar_gemini
    nem tenta a chamada HTTP -- confirma via mock nunca chamado."""
    user = UserFactory()
    db_session.add(UserQuota(user_id=user.id, daily_tokens_consumed=50_000, daily_limit=50_000, last_reset_date=date.today()))
    db_session.commit()

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post") as mock_post:
        try:
            _chamar_gemini("qualquer prompt", user.id, db_session)
            assert False, "deveria ter lançado QuotaExceededError"
        except QuotaExceededError:
            pass

    assert not mock_post.called


def test_chamar_gemini_debita_a_estimativa_antes_da_chamada(db_session):
    from unittest.mock import Mock

    user = UserFactory()
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    resp.raise_for_status.return_value = None

    prompt = "x" * 400  # ~100 tokens (400 chars / 4)
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=resp):
        _chamar_gemini(prompt, user.id, db_session)

    quota = db_session.get(UserQuota, user.id)
    assert quota.daily_tokens_consumed == 100


def test_isolamento_entre_usuarios(db_session):
    """A cota de um usuário nunca afeta a de outro."""
    user_a = UserFactory()
    user_b = UserFactory()
    db_session.add(UserQuota(user_id=user_a.id, daily_tokens_consumed=50_000, daily_limit=50_000, last_reset_date=date.today()))
    db_session.commit()

    assert check_and_consume_tokens(user_a.id, 1, db_session) is False
    assert check_and_consume_tokens(user_b.id, 1, db_session) is True
