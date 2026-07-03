"""Teste do endpoint de geração por IA — com a chamada ao Gemini SIMULADA (mock)."""
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def logar(email, senha="senha123"):
    client.post("/auth/register", json={"email": email, "password": senha})
    r = client.post("/auth/login", data={"username": email, "password": senha})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

vini = logar("vini@estalo.dev")
deck = client.post("/decks", json={"title": "Zero Trust"}, headers=vini).json()
did = deck["id"]

print("1) Gerar cards por IA (resposta do Gemini simulada)...")
fake = [
    {
        "front": "O que e Zero Trust?",
        "back": "Modelo: nunca confie, sempre verifique",
        "distractors": ["Confiar em tudo dentro da rede", "Autenticar so uma vez", "Ignorar a origem da requisicao"],
        "explanation": "Zero Trust parte do principio de verificacao continua, nunca implicita.",
    },
    {
        "front": "Principio central?",
        "back": "Verificacao continua de identidade",
        "distractors": ["Perimetro de rede fixo", "Confianca implicita", "Acesso irrestrito"],
        "explanation": "O principio central e nunca confiar automaticamente, sempre validar.",
    },
]
# Troca a funcao gerar_cards_completos por uma que devolve o fake, sem chamar a internet.
with patch("app.routers.cards.gerar_cards_completos", return_value=fake):
    r = client.post(f"/decks/{did}/cards/generate",
                    json={"text": "Zero Trust e um modelo de seguranca...", "quantity": 2},
                    headers=vini)
print("   status:", r.status_code)
cards = r.json()
print("   cards gerados:", len(cards))
print("   origem do primeiro:", cards[0]["source"])
assert r.status_code == 201
assert len(cards) == 2
assert all(c["source"] == "ai" for c in cards)  # todos marcados como IA
print("   OK — cards salvos no deck com source='ai'\n")

print("2) Os cards gerados aparecem na listagem normal do deck...")
todos = client.get(f"/decks/{did}/cards", headers=vini).json()
print("   total no deck:", len(todos))
assert len(todos) == 2
print("   OK\n")

print("3) Sem chave configurada, a API responde erro 502 (nao 500)...")
from app.services.ai import IAError
with patch("app.routers.cards.gerar_cards_completos", side_effect=IAError("Chave do Gemini nao configurada")):
    r = client.post(f"/decks/{did}/cards/generate",
                    json={"text": "qualquer texto aqui", "quantity": 3},
                    headers=vini)
print("   status:", r.status_code, "| detalhe:", r.json().get("detail"))
assert r.status_code == 502
print("   OK — erro tratado com elegancia, nao quebrou o servidor\n")

print("4) ISOLAMENTO: intruso nao gera cards no deck do Vini...")
intruso = logar("intruso@estalo.dev")
with patch("app.routers.cards.gerar_cards_completos", return_value=fake):
    r = client.post(f"/decks/{did}/cards/generate",
                    json={"text": "texto de invasao", "quantity": 2},
                    headers=intruso)
print("   status:", r.status_code)
assert r.status_code == 404
print("   OK\n")

print("=== TODOS OS TESTES DE IA PASSARAM ===")
