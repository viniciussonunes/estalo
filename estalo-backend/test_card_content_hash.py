"""Teste do content_hash sendo gerado/recalculado nativamente na persistência de cards."""
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import Card
from app.models.card import calcular_content_hash

client = TestClient(app)


def logar(email, senha="senha123"):
    client.post("/auth/register", json={"email": email, "password": senha})
    r = client.post("/auth/login", data={"username": email, "password": senha})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def hash_no_banco(card_id):
    db = SessionLocal()
    card = db.query(Card).filter(Card.id == card_id).first()
    h = card.content_hash
    db.close()
    return h


vini = logar("hash_vini@estalo.dev")
deck = client.post("/decks", json={"title": "Deck Hash"}, headers=vini).json()

print("1) Card manual nasce com content_hash já preenchido e correto...")
c1 = client.post(
    f"/decks/{deck['id']}/cards",
    json={"front": "O que é HTTP?", "back": "Protocolo de transferência de hipertexto"},
    headers=vini,
).json()
esperado = calcular_content_hash("O que é HTTP?", "Protocolo de transferência de hipertexto")
assert hash_no_banco(c1["id"]) == esperado
print("   OK\n")

print("2) Card gerado por IA nasce com content_hash correto (Gemini real)...")
gerados = client.post(
    f"/decks/{deck['id']}/cards/generate",
    json={"text": "O Sol é uma estrela. A Lua é um satélite natural da Terra.", "quantity": 2},
    headers=vini,
)
assert gerados.status_code == 201, gerados.text
for c in gerados.json():
    db_card = SessionLocal()
    card_row = db_card.query(Card).filter(Card.id == c["id"]).first()
    esperado_ia = calcular_content_hash(card_row.front, card_row.back)
    assert card_row.content_hash == esperado_ia, f"hash não bate pro card {c['id']}"
    db_card.close()
print(f"   OK — {len(gerados.json())} cards de IA com hash correto\n")

print("3) Editar só o front recalcula o hash (consistency check)...")
hash_antes = hash_no_banco(c1["id"])
client.patch(f"/cards/{c1['id']}", json={"front": "O que é o protocolo HTTP?"}, headers=vini)
hash_depois = hash_no_banco(c1["id"])
esperado_depois = calcular_content_hash("O que é o protocolo HTTP?", "Protocolo de transferência de hipertexto")
assert hash_depois == esperado_depois
assert hash_depois != hash_antes, "hash deveria ter mudado depois de editar o front"
print("   OK\n")

print("4) Editar só o back também recalcula...")
client.patch(f"/cards/{c1['id']}", json={"back": "Protocolo de aplicação da web"}, headers=vini)
hash_final = hash_no_banco(c1["id"])
esperado_final = calcular_content_hash("O que é o protocolo HTTP?", "Protocolo de aplicação da web")
assert hash_final == esperado_final
assert hash_final != hash_depois
print("   OK\n")

print("5) PATCH vazio (nem front nem back) não mexe no hash...")
antes_vazio = hash_no_banco(c1["id"])
client.patch(f"/cards/{c1['id']}", json={}, headers=vini)
depois_vazio = hash_no_banco(c1["id"])
assert antes_vazio == depois_vazio
print("   OK\n")

print("Todos os testes de content_hash na persistência passaram.")
