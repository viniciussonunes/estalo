"""Teste do ciclo de estudo: fila de cards vencidos + motor SM-2 espacando de verdade."""
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import Review

client = TestClient(app)

def logar(email, senha="senha123"):
    client.post("/auth/register", json={"email": email, "password": senha})
    r = client.post("/auth/login", data={"username": email, "password": senha})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

vini = logar("vini@estalo.dev")

# Monta deck com 2 cards
deck = client.post("/decks", json={"title": "SC-900 Fundamentos"}, headers=vini).json()
c1 = client.post(f"/decks/{deck['id']}/cards", json={"front": "O que e MFA?", "back": "Multifator"}, headers=vini).json()
c2 = client.post(f"/decks/{deck['id']}/cards", json={"front": "O que e SSO?", "back": "Single Sign-On"}, headers=vini).json()
did = deck["id"]

print("1) Stats iniciais (2 cards novos, 2 prontos pra estudar)...")
s = client.get(f"/study/decks/{did}/stats", headers=vini).json()
print("  ", s)
assert s == {"total_cards": 2, "due_now": 2, "new_cards": 2}
print("   OK\n")

print("2) Pegar o proximo card pra estudar...")
prox = client.get(f"/study/decks/{did}/next", headers=vini).json()
print("   card:", prox["front"], "| repeticoes:", prox["repetitions"])
assert prox is not None
print("   OK\n")

print("3) Acertei FACIL (nota 5) -> deve sumir da fila por dias...")
r = client.post(f"/study/cards/{prox['card_id']}/answer", json={"quality": 5}, headers=vini).json()
print(f"   novo intervalo: {r['interval']} dia(s) | proxima revisao: {r['next_due'][:10]}")
assert r["interval"] >= 1
print("   OK\n")

print("4) Stats agora: 1 card ainda vencido (o que nao estudei)...")
s = client.get(f"/study/decks/{did}/stats", headers=vini).json()
print("  ", s)
assert s["due_now"] == 1 and s["new_cards"] == 1
print("   OK — card estudado saiu da fila de hoje\n")

print("5) Estudar o segundo card e ERRAR (nota 1) -> volta amanha...")
prox2 = client.get(f"/study/decks/{did}/next", headers=vini).json()
print("   proximo card:", prox2["front"])
r = client.post(f"/study/cards/{prox2['card_id']}/answer", json={"quality": 1}, headers=vini).json()
print(f"   errou -> intervalo: {r['interval']} dia(s), repeticoes zeradas: {r['repetitions']}")
assert r["interval"] == 1 and r["repetitions"] == 0
print("   OK — card errado volta logo\n")

print("6) Agora a fila de HOJE esta vazia (os dois tem due_date no futuro)...")
prox3 = client.get(f"/study/decks/{did}/next", headers=vini).json()
print("   proximo card:", prox3)
assert prox3 is None
print("   OK — nada vencido agora\n")

print("7) Simular passagem do tempo: forco o card errado a vencer e ele reaparece...")
db = SessionLocal()
rev = db.query(Review).filter(Review.card_id == prox2["card_id"]).first()
rev.due_date = datetime.utcnow() - timedelta(days=2)  # finge que ja venceu
db.commit()
db.close()
prox4 = client.get(f"/study/decks/{did}/next", headers=vini).json()
print("   card que reapareceu:", prox4["front"] if prox4 else None)
assert prox4 is not None and prox4["card_id"] == prox2["card_id"]
print("   OK — card vencido voltou pra fila\n")

print("=== TODOS OS TESTES DE ESTUDO PASSARAM ===")
