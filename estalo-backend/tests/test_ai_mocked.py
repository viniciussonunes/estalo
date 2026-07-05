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

FIXTURES = Path(__file__).parent / "fixtures"


def _resposta_gemini_mock():
    corpo = json.loads((FIXTURES / "gemini_response_success.json").read_text())
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = corpo
    resp.raise_for_status.return_value = None
    return resp


def test_gerar_cards_completos_com_gemini_mockado():
    # patch.object na GEMINI_API_KEY também -- sem isso, o teste dependeria
    # de existir uma chave real configurada no ambiente (settings.py
    # levanta IAError antes mesmo de chamar httpx.post se a chave estiver
    # vazia), o que quebraria justamente o "determinístico, sem rede" que
    # este arquivo existe pra garantir.
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post", return_value=_resposta_gemini_mock()) as mock_post:
        cards = gerar_cards_completos("Geografia da Europa", 2)

    assert mock_post.called
    assert len(cards) == 2
    assert cards[0]["front"] == "Qual é a capital da França?"
    assert cards[0]["back"] == "Paris"
    assert len(cards[0]["distractors"]) == 3
    assert "Paris" in cards[0]["explanation"]
    assert cards[1]["back"] == "Roma"


def test_gerar_cards_completos_nao_faz_nenhuma_chamada_de_rede_real():
    """Prova que o teste acima é hermético: se o código tentasse mesmo
    assim ir pra rede (bug de patch mal aplicado), httpx.post real
    lançaria erro de conexão -- aqui garantimos que SÓ o mock é chamado."""
    with patch.object(settings, "GEMINI_API_KEY", "chave-fake-de-teste"), \
         patch("app.services.ai.httpx.post") as mock_post:
        mock_post.return_value = _resposta_gemini_mock()
        gerar_cards_completos("Qualquer texto", 2)
        mock_post.assert_called_once()
        # confirma que foi feita exatamente 1 chamada -- nenhum retry
        # aconteceu, porque o mock nunca "falhou" de propósito
