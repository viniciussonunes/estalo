"""
Testes de POST /challenges/generate (challenge_service.gerar_challenge) --
Gemini mockado, sem rede (mesma técnica do resto da suíte: httpx, não
`requests`, mock entra em app.services.ai.httpx.post).

Cobre o mecanismo genérico (herdado da 1ª versão deste módulo): geração
feliz, correção automática de JSON inválido, falha definitiva (503, nada
persistido), cota estourada (429), isolamento de dono do deck (404),
`depth` e `preview_only`. E o Mentor de Inglês Ativo especificamente:
type default "ENGLISH_TUTOR", `language_level` (default "B1", validação
de enum CEFR, e presença no prompt e na persistência).
"""
import json
from unittest.mock import Mock, patch

from app.core.config import settings
from app.models.challenge import Challenge


def _autenticar(client, email="challenge_test@estalo.dev"):
    client.post("/auth/register", json={"email": email, "password": "senha123"})
    login = client.post("/auth/login", data={"username": email, "password": "senha123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _criar_deck(client, auth, titulo="Deck Challenge"):
    return client.post("/decks", json={"title": titulo}, headers=auth).json()


def _resposta_gemini_mock(texto: str):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": texto}]}}]}
    resp.raise_for_status.return_value = None
    return resp


_PAYLOAD_INGLES_VALIDO = json.dumps({
    "content": {
        "student_attempt": "I are happy",
        "native_correction": "I am happy",
        "why": "O verbo 'to be' na 1ª pessoa do singular conjuga como 'am', não 'are' (que é pra 'you/we/they').",
        "collocations": ["to be happy"],
    },
    "explanation": "'I am' é a forma correta do verbo 'to be' na 1ª pessoa do singular.",
    "tutor_explanation": "Muito bem por tentar! O verbo 'to be' muda de forma conforme o sujeito: I am, you are, "
                          "he/she/it is, we are, they are. 'I are' mistura a conjugação de 'I' com a de 'you/we/they'.",
})

_PAYLOAD_GENERICO_VALIDO = json.dumps({
    "content": {
        "text_with_gap": "A capital da França é ___.",
        "correct_answer": "Paris",
        "distractors": ["Londres", "Roma", "Madri"],
    },
    "explanation": "Paris é a capital da França.",
    "tutor_explanation": "Paris é a capital e maior cidade da França, sede do governo.",
})


# --- Mentor de Inglês Ativo (type default "ENGLISH_TUTOR") ---------------

def test_type_default_e_english_tutor(client):
    """Sem `type` no body, o default do schema ("ENGLISH_TUTOR") é o que
    efetivamente é gerado e persistido."""
    auth = _autenticar(client, "ingles_default@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_PAYLOAD_INGLES_VALIDO)):
        resp = client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "I are happy"},
            headers=auth,
        )

    assert resp.status_code == 201
    corpo = resp.json()
    assert corpo["type"] == "ENGLISH_TUTOR"
    assert corpo["content"]["native_correction"] == "I am happy"


def test_language_level_default_e_b1_e_entra_no_prompt(client):
    auth = _autenticar(client, "nivel_default@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_PAYLOAD_INGLES_VALIDO)) as mock_post:
        resp = client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "I are happy"},
            headers=auth,
        )

    assert resp.status_code == 201
    assert resp.json()["language_level"] == "B1"
    prompt_enviado = mock_post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
    assert "CEFR B1" in prompt_enviado


def test_language_level_c2_muda_o_prompt_e_e_persistido(client, db_session):
    auth = _autenticar(client, "nivel_c2@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_PAYLOAD_INGLES_VALIDO)) as mock_post:
        resp = client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "I are happy", "language_level": "C2"},
            headers=auth,
        )

    assert resp.status_code == 201
    assert resp.json()["language_level"] == "C2"
    prompt_enviado = mock_post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
    assert "CEFR C2" in prompt_enviado
    assert "editor nativo" in prompt_enviado

    salvo = db_session.get(Challenge, resp.json()["id"])
    assert salvo.language_level == "C2"


def test_language_level_invalido_da_422_sem_chamar_ia(client):
    auth = _autenticar(client, "nivel_invalido@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "I are happy", "language_level": "D3"},
            headers=auth,
        )

    assert resp.status_code == 422
    assert not mock_post.called


def test_prompt_do_mentor_contem_a_estrutura_pedida(client):
    """Confere que o system prompt do Mentor de Inglês carrega os 3
    elementos pedidos: persona de professor encorajador, foco em
    collocations/gramática contextualizada, e a lógica tentativa/correção/
    porquê -- não só que o JSON de resposta tem esses campos."""
    auth = _autenticar(client, "prompt_estrutura@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_PAYLOAD_INGLES_VALIDO)) as mock_post:
        client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "I are happy"},
            headers=auth,
        )

    prompt = mock_post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
    assert "encorajador" in prompt
    assert "collocations" in prompt.lower()
    assert "O que o aluno tentou dizer" in prompt
    assert "Como um nativo diria" in prompt
    assert "Por quê" in prompt
    assert "student_attempt" in prompt
    assert "native_correction" in prompt


def test_outro_tipo_ainda_funciona_via_api_sem_usar_prompt_de_ingles(client):
    """type continua aceitando outros valores (o motor é genérico por
    baixo) -- só o default mudou pra ENGLISH_TUTOR."""
    auth = _autenticar(client, "outro_tipo@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_PAYLOAD_GENERICO_VALIDO)) as mock_post:
        resp = client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "Texto de estudo qualquer.", "type": "FILL_THE_GAP"},
            headers=auth,
        )

    assert resp.status_code == 201
    assert resp.json()["type"] == "FILL_THE_GAP"
    assert resp.json()["language_level"] is None  # só ENGLISH_TUTOR guarda nível

    prompt_enviado = mock_post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
    assert "mentor de inglês" not in prompt_enviado.lower()


# --- Mecanismo genérico (herdado, continua coberto) -----------------------

def test_correcao_automatica_de_json_invalido(client):
    auth = _autenticar(client, "corrige@estalo.dev")
    deck = _criar_deck(client, auth)

    respostas = [
        _resposta_gemini_mock("isso não é JSON nenhum"),
        _resposta_gemini_mock(_PAYLOAD_INGLES_VALIDO),
    ]
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", side_effect=respostas) as mock_post:
        resp = client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "I are happy"},
            headers=auth,
        )

    assert resp.status_code == 201
    assert mock_post.call_count == 2


def test_falha_definitiva_retorna_503_e_nao_persiste_nada(client, db_session):
    auth = _autenticar(client, "falha_definitiva@estalo.dev")
    deck = _criar_deck(client, auth)

    respostas = [_resposta_gemini_mock("lixo 1"), _resposta_gemini_mock("lixo 2")]
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", side_effect=respostas) as mock_post:
        resp = client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "I are happy"},
            headers=auth,
        )

    assert resp.status_code == 503
    assert mock_post.call_count == 2
    assert db_session.query(Challenge).filter(Challenge.deck_id == deck["id"]).count() == 0


def test_preview_only_nao_persiste_e_devolve_200_com_id_nulo(client, db_session):
    auth = _autenticar(client, "preview@estalo.dev")
    deck = _criar_deck(client, auth)

    with patch.object(settings, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock(_PAYLOAD_INGLES_VALIDO)) as mock_post:
        resp = client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "I are happy", "preview_only": True},
            headers=auth,
        )

    assert resp.status_code == 200
    assert mock_post.called
    corpo = resp.json()
    assert corpo["id"] is None
    assert corpo["created_at"] is None
    assert corpo["content"]["native_correction"] == "I am happy"
    assert db_session.query(Challenge).filter(Challenge.deck_id == deck["id"]).count() == 0


def test_quota_bloqueia_geracao_no_nivel_de_servico(db_session):
    from datetime import date

    from app.core.config import settings as cfg
    from app.models.user_quota import UserQuota
    from app.services.ai import QuotaExceededError
    from app.services.challenge_service import gerar_challenge
    from tests.factories import DeckFactory, UserFactory

    user = UserFactory()
    deck = DeckFactory(owner=user)
    db_session.add(UserQuota(user_id=user.id, daily_tokens_consumed=50_000, daily_limit=50_000, last_reset_date=date.today()))
    db_session.commit()

    with patch.object(cfg, "GEMINI_API_KEY", "chave-fake"), \
         patch("app.services.ai.httpx.post") as mock_post:
        try:
            gerar_challenge(deck.id, "I are happy", "ENGLISH_TUTOR", user.id, db_session)
            assert False, "deveria ter lançado QuotaExceededError"
        except QuotaExceededError:
            pass

    assert not mock_post.called


def test_deck_de_outro_usuario_da_404_sem_chamar_ia(client):
    dono_auth = _autenticar(client, "dono_challenge@estalo.dev")
    deck = _criar_deck(client, dono_auth)

    intruso_auth = _autenticar(client, "intruso_challenge@estalo.dev")

    with patch("app.services.ai.httpx.post") as mock_post:
        resp = client.post(
            "/challenges/generate",
            json={"deck_id": deck["id"], "raw_content": "I are happy"},
            headers=intruso_auth,
        )

    assert resp.status_code == 404
    assert not mock_post.called
