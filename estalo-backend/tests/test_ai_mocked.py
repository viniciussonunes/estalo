"""
Testes de IA determinísticos, sem rede — interceptando a chamada ao
Gemini com unittest.mock.

Nota: o pedido original sugeria `responses` OU `unittest.mock`. `responses`
intercepta a lib `requests` — app/services/ai.py usa `httpx.post()`
(confirmado em ai.py:57), então `responses` simplesmente não interceptaria
nada aqui (são bibliotecas HTTP diferentes, sem compatibilidade entre si).
Fui de `unittest.mock` (stdlib, e já cobre o caso).

Isso é COMPLEMENTAR aos testes existentes que batem no Gemini de verdade
(test_ai.py, test_card_content_hash.py, na raiz do projeto) — aqueles dão
confiança de integração real; este dá velocidade e determinismo, sem
depender de rede nem de GEMINI_API_KEY estar configurada no ambiente.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.config import settings
from app.services.ai import gerar_cards_completos
from tests.factories import UserFactory

FIXTURES = Path(__file__).parent / "fixtures"


def _resposta_gemini_mock():
    corpo = json.loads((FIXTURES / "gemini_response_success.json").read_text())
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = corpo
    resp.raise_for_status.return_value = None
    return resp


def test_gerar_cards_completos_com_gemini_mockado(db_session):
    # patch.object na GEMINI_API_KEY também -- sem isso, o teste dependeria
    # de existir uma chave real configurada no ambiente (settings.py
    # levanta IAError antes mesmo de chamar httpx.post se a chave estiver
    # vazia), o que quebraria justamente o "determinístico, sem rede" que
    # este arquivo existe pra garantir.
    user = UserFactory()
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()) as mock_post:
        cards = gerar_cards_completos("Geografia da Europa", 2, user.id, db_session)

    assert mock_post.called
    assert len(cards) == 2
    assert cards[0]["front"] == "Qual é a capital da França?"
    assert cards[0]["back"] == "Paris"
    assert len(cards[0]["distractors"]) == 3
    assert "Paris" in cards[0]["explanation"]
    assert cards[1]["back"] == "Roma"


def test_gerar_cards_completos_descarta_card_com_distractor_muito_curto(db_session):
    """Bug real reportado por usuário: a IA às vezes ignora a regra de
    tamanho do prompt e devolve um distractor bem mais curto que o 'back',
    dando uma pista visual da resposta certa. _distractors_equilibrados()
    (ai.py) é a rede de segurança pra esse caso -- o card inteiro é
    descartado (mesmo tratamento já dado a JSON malformado) em vez de ir
    pro usuário com uma alternativa óbvia."""
    corpo = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": json.dumps([
                        {
                            "front": "Card bom",
                            "back": "Resposta correta bem detalhada e completa sobre o assunto",
                            "distractors": [
                                "Alternativa incorreta igualmente detalhada e completa",
                                "Outra alternativa incorreta também bem elaborada aqui",
                                "Mais uma alternativa incorreta com tamanho parecido",
                            ],
                            "explanation": "Explicação.",
                        },
                        {
                            "front": "Card com distractor curto demais",
                            "back": "Resposta correta bem detalhada e completa sobre o assunto",
                            "distractors": ["curta", "Outra alternativa incorreta também bem elaborada aqui", "Mais uma alternativa incorreta com tamanho parecido"],
                            "explanation": "Explicação.",
                        },
                    ], ensure_ascii=False)
                }]
            }
        }]
    }
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = corpo
    resp.raise_for_status.return_value = None

    user = UserFactory()
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=resp):
        cards = gerar_cards_completos("Qualquer texto", 2, user.id, db_session)

    assert len(cards) == 1
    assert cards[0]["front"] == "Card bom"


def test_gerar_cards_completos_nao_faz_nenhuma_chamada_de_rede_real(db_session):
    """Prova que o teste acima é hermético: se o código tentasse mesmo
    assim ir pra rede (bug de patch mal aplicado), httpx.post real
    lançaria erro de conexão -- aqui garantimos que SÓ o mock é chamado."""
    user = UserFactory()
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post") as mock_post:
        mock_post.return_value = _resposta_gemini_mock()
        gerar_cards_completos("Qualquer texto", 2, user.id, db_session)
        mock_post.assert_called_once()
        # confirma que foi feita exatamente 1 chamada -- nenhum retry
        # aconteceu, porque o mock nunca "falhou" de propósito
