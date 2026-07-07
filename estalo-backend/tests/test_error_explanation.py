"""
Testes do Tutor Inteligente Evolutivo (explicação de erro por alternativa,
cache versionado + feedback). Gemini mockado, sem rede (mesma técnica de
test_tutor_endpoint.py/test_ai_mocked.py: httpx, não `requests`).

Cobre: Miss cria v1 + log, Hit não chama IA de novo, feedback positivo
não muda nada, feedback negativo refina e incrementa versão, idempotência
por motivo repetido, teto de MAX_VERSAO, unicidade (card_id,
alternativa_escolhida) real no banco, isolamento entre usuários, e
fallback 503/429.
"""
from unittest.mock import Mock, patch

from app.core.config import settings
from app.models.explanation_cache import ExplanationCache
from app.models.explanation_log import ExplanationLog
from app.services.error_explanation_service import MAX_VERSAO, explicar_erro, refinar_explicacao
from tests.factories import CardFactory, UserFactory


def _autenticar(client, email="erro_test@estalo.dev"):
    client.post("/auth/register", json={"email": email, "password": "senha123"})
    login = client.post("/auth/login", data={"username": email, "password": "senha123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _resposta_gemini_mock(texto="A alternativa X está errada porque..."):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": texto}]}}]}
    resp.raise_for_status.return_value = None
    return resp


def _criar_card(client, auth, front="Qual é a capital da França?", back="Paris"):
    deck = client.post("/decks", json={"title": "Deck Erro"}, headers=auth).json()
    card = client.post(f"/decks/{deck['id']}/cards", json={"front": front, "back": back}, headers=auth).json()
    return card


# --- Nível de serviço (unit) ---

def test_explicar_erro_miss_cria_cache_e_log(db_session):
    user = UserFactory()
    card = CardFactory()
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()) as mock_post:
        resultado = explicar_erro(card.id, "Pergunta?", "Certa", "Errada", user.id, db_session)

    assert mock_post.called
    assert resultado.versao == 1
    assert resultado.limite_atingido is False

    cache = db_session.query(ExplanationCache).filter_by(card_id=card.id, alternativa_escolhida="Errada").first()
    assert cache is not None
    assert cache.versao == 1
    assert cache.motivo_rejeicao_mais_recente is None

    logs = db_session.query(ExplanationLog).filter_by(explanation_cache_id=cache.id).all()
    assert len(logs) == 1
    assert logs[0].versao == 1
    assert logs[0].motivo_rejeicao is None


def test_explicar_erro_hit_nao_chama_gemini_de_novo(db_session):
    user = UserFactory()
    card = CardFactory()
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()) as mock_post:
        explicar_erro(card.id, "Pergunta?", "Certa", "Errada", user.id, db_session)
    assert mock_post.call_count == 1

    with patch("app.services.ai.httpx.post") as mock_post_2:
        resultado = explicar_erro(card.id, "Pergunta?", "Certa", "Errada", user.id, db_session)

    assert not mock_post_2.called
    assert resultado.versao == 1


def test_refinar_incrementa_versao_e_grava_log(db_session):
    user = UserFactory()
    card = CardFactory()
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("v1")):
        explicar_erro(card.id, "Pergunta?", "Certa", "Errada", user.id, db_session)

    cache = db_session.query(ExplanationCache).filter_by(card_id=card.id, alternativa_escolhida="Errada").first()

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("v2, melhor")) as mock_post:
        resultado = refinar_explicacao(cache, "Pergunta?", "Certa", "muito confuso", user.id, db_session)

    assert mock_post.called
    assert resultado.versao == 2
    assert resultado.explanation == "v2, melhor"
    assert cache.motivo_rejeicao_mais_recente == "muito confuso"

    logs = db_session.query(ExplanationLog).filter_by(explanation_cache_id=cache.id).order_by(ExplanationLog.versao).all()
    assert [l.versao for l in logs] == [1, 2]
    assert logs[1].motivo_rejeicao == "muito confuso"


def test_refinar_idempotente_por_mesmo_motivo(db_session):
    """Retry com o MESMO motivo (ex: reenvio por queda de conexão) não
    gasta IA de novo nem incrementa versão -- é tratado como no-op."""
    user = UserFactory()
    card = CardFactory()
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("v1")):
        explicar_erro(card.id, "Pergunta?", "Certa", "Errada", user.id, db_session)
    cache = db_session.query(ExplanationCache).filter_by(card_id=card.id, alternativa_escolhida="Errada").first()

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("v2")):
        refinar_explicacao(cache, "Pergunta?", "Certa", "confuso", user.id, db_session)
    assert cache.versao == 2

    with patch("app.services.ai.httpx.post") as mock_post_retry:
        resultado = refinar_explicacao(cache, "Pergunta?", "Certa", "confuso", user.id, db_session)

    assert not mock_post_retry.called
    assert resultado.versao == 2  # não incrementou de novo


def test_refinar_respeita_teto_max_versao(db_session):
    user = UserFactory()
    card = CardFactory()
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("v1")):
        explicar_erro(card.id, "Pergunta?", "Certa", "Errada", user.id, db_session)
    cache = db_session.query(ExplanationCache).filter_by(card_id=card.id, alternativa_escolhida="Errada").first()

    # Refina até bater no teto -- cada motivo diferente pra não cair no
    # atalho de idempotência.
    for i in range(MAX_VERSAO - 1):
        with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
             patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(f"v{i+2}")):
            refinar_explicacao(cache, "Pergunta?", "Certa", f"motivo {i}", user.id, db_session)
    assert cache.versao == MAX_VERSAO

    with patch("app.services.ai.httpx.post") as mock_post_no_teto:
        resultado = refinar_explicacao(cache, "Pergunta?", "Certa", "motivo final", user.id, db_session)

    assert not mock_post_no_teto.called
    assert resultado.limite_atingido is True
    assert resultado.versao == MAX_VERSAO


def test_indice_unico_card_alternativa_e_real_no_banco(db_session):
    """Confirma que a unicidade (card_id, alternativa_escolhida) é
    imposta pelo próprio banco, não só pela lógica do service."""
    from sqlalchemy.exc import IntegrityError

    card = CardFactory()
    db_session.add(ExplanationCache(card_id=card.id, alternativa_escolhida="X", texto_explicacao_atual="a"))
    db_session.commit()

    db_session.add(ExplanationCache(card_id=card.id, alternativa_escolhida="X", texto_explicacao_atual="b"))
    try:
        db_session.commit()
        assert False, "deveria ter violado o índice único"
    except IntegrityError:
        db_session.rollback()


def test_excluir_card_apaga_explanation_cache_e_log_em_cascata(db_session):
    """Regressão: achado testando exclusão de deck de ponta a ponta em
    produção. Apagar um card (e por cascata seu ExplanationCache) quebrava
    no Postgres real com ForeignKeyViolation -- explanation_log ainda
    referenciava a linha que o SQLAlchemy tentou apagar (faltava o
    relationship com cascade="all, delete-orphan" entre as duas tabelas).

    SQLite (usado aqui) não enforce FK por padrão, então o bug NUNCA
    lançava exceção neste ambiente -- por isso o teste confere o efeito
    que realmente importa (nenhuma linha órfã sobra em nenhuma das duas
    tabelas), não só "não deu erro"."""
    user = UserFactory()
    card = CardFactory()
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()):
        explicar_erro(card.id, "Pergunta?", "Certa", "Errada", user.id, db_session)

    cache = db_session.query(ExplanationCache).filter_by(card_id=card.id).first()
    assert cache is not None
    assert db_session.query(ExplanationLog).filter_by(explanation_cache_id=cache.id).count() == 1

    db_session.delete(card)
    db_session.commit()  # não pode lançar IntegrityError

    assert db_session.query(ExplanationCache).filter_by(card_id=card.id).count() == 0
    assert db_session.query(ExplanationLog).filter_by(explanation_cache_id=cache.id).count() == 0


# --- Nível de endpoint (integração via HTTP) ---

def test_endpoint_explain_error_cria_e_reusa_cache(client):
    auth = _autenticar(client)
    card = _criar_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()) as mock_post:
        resp1 = client.post(
            f"/study/cards/{card['id']}/error-explanation",
            json={"alternativa_escolhida": "Alternativa Errada"},
            headers=auth,
        )
    assert resp1.status_code == 200
    assert resp1.json()["versao"] == 1
    assert mock_post.call_count == 1

    with patch("app.services.ai.httpx.post") as mock_post_2:
        resp2 = client.post(
            f"/study/cards/{card['id']}/error-explanation",
            json={"alternativa_escolhida": "Alternativa Errada"},
            headers=auth,
        )
    assert resp2.status_code == 200
    assert not mock_post_2.called


def test_endpoint_feedback_positivo_nao_muda_nada(client):
    auth = _autenticar(client, "erro_pos@estalo.dev")
    card = _criar_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()):
        client.post(
            f"/study/cards/{card['id']}/error-explanation",
            json={"alternativa_escolhida": "Errada"},
            headers=auth,
        )

    resp = client.post(
        f"/study/cards/{card['id']}/error-explanation/feedback",
        json={"alternativa_escolhida": "Errada", "positivo": True},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json()["versao"] == 1


def test_endpoint_feedback_negativo_sem_motivo_da_422(client):
    auth = _autenticar(client, "erro_semmotivo@estalo.dev")
    card = _criar_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()):
        client.post(
            f"/study/cards/{card['id']}/error-explanation",
            json={"alternativa_escolhida": "Errada"},
            headers=auth,
        )

    resp = client.post(
        f"/study/cards/{card['id']}/error-explanation/feedback",
        json={"alternativa_escolhida": "Errada", "positivo": False},
        headers=auth,
    )
    assert resp.status_code == 422


def test_endpoint_feedback_negativo_refina(client):
    auth = _autenticar(client, "erro_refina@estalo.dev")
    card = _criar_card(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("v1")):
        client.post(
            f"/study/cards/{card['id']}/error-explanation",
            json={"alternativa_escolhida": "Errada"},
            headers=auth,
        )

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock("v2 refinada")):
        resp = client.post(
            f"/study/cards/{card['id']}/error-explanation/feedback",
            json={"alternativa_escolhida": "Errada", "positivo": False, "motivo": "não ficou claro"},
            headers=auth,
        )

    assert resp.status_code == 200
    assert resp.json()["versao"] == 2
    assert resp.json()["explanation"] == "v2 refinada"


def test_endpoint_feedback_de_explicacao_inexistente_da_404(client):
    auth = _autenticar(client, "erro_404@estalo.dev")
    card = _criar_card(client, auth)

    resp = client.post(
        f"/study/cards/{card['id']}/error-explanation/feedback",
        json={"alternativa_escolhida": "Nunca pedida", "positivo": True},
        headers=auth,
    )
    assert resp.status_code == 404


def test_endpoint_isolamento_entre_usuarios(client):
    dono_auth = _autenticar(client, "erro_dono@estalo.dev")
    card = _criar_card(client, dono_auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()):
        client.post(
            f"/study/cards/{card['id']}/error-explanation",
            json={"alternativa_escolhida": "Errada"},
            headers=dono_auth,
        )

    intruso_auth = _autenticar(client, "erro_intruso@estalo.dev")

    resp_explain = client.post(
        f"/study/cards/{card['id']}/error-explanation",
        json={"alternativa_escolhida": "Errada"},
        headers=intruso_auth,
    )
    assert resp_explain.status_code == 404

    resp_feedback = client.post(
        f"/study/cards/{card['id']}/error-explanation/feedback",
        json={"alternativa_escolhida": "Errada", "positivo": True},
        headers=intruso_auth,
    )
    assert resp_feedback.status_code == 404


def test_endpoint_erro_da_ia_retorna_503(client):
    auth = _autenticar(client, "erro_503@estalo.dev")
    card = _criar_card(client, auth)

    resp_erro = Mock()
    resp_erro.status_code = 503
    resp_erro.raise_for_status.side_effect = Exception("indisponível")

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=resp_erro):
        resp = client.post(
            f"/study/cards/{card['id']}/error-explanation",
            json={"alternativa_escolhida": "Errada"},
            headers=auth,
        )

    assert resp.status_code == 503
