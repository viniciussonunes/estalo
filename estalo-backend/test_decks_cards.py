"""Teste de ponta a ponta de decks e cards, com isolamento entre usuários."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def logar(email, senha="senha123"):
    client.post("/auth/register", json={"email": email, "password": senha})
    r = client.post("/auth/login", data={"username": email, "password": senha})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

vini = logar("vini@estalo.dev")
outro = logar("intruso@estalo.dev")

print("1) Criar pasta + deck dentro dela...")
pasta = client.post("/folders", json={"name": "SC-900"}, headers=vini).json()
deck = client.post("/decks", json={"title": "Metodos de MFA", "folder_id": pasta["id"]}, headers=vini).json()
print(f"   deck '{deck['title']}' criado na pasta {deck['folder_id']}")
assert deck["folder_id"] == pasta["id"]
print("   OK\n")

print("2) Criar deck numa pasta de OUTRO usuario (DEVE FALHAR)...")
r = client.post("/decks", json={"title": "invasao", "folder_id": pasta["id"]}, headers=outro)
print("   status:", r.status_code)
assert r.status_code == 404
print("   OK — nao da pra criar deck na pasta alheia\n")

print("3) Adicionar cards no deck (um manual, um 'ai')...")
c1 = client.post(f"/decks/{deck['id']}/cards",
                 json={"front": "O que e MFA?", "back": "Autenticacao multifator", "source": "ai"},
                 headers=vini).json()
c2 = client.post(f"/decks/{deck['id']}/cards",
                 json={"front": "Cite 3 fatores", "back": "Algo que sabe, tem, e"},
                 headers=vini).json()
print(f"   card 1 (origem: {c1['source']}), card 2 (origem: {c2['source']})")
assert c1["source"] == "ai" and c2["source"] == "manual"
print("   OK — origem registrada certinho\n")

print("4) Listar cards do deck...")
cards = client.get(f"/decks/{deck['id']}/cards", headers=vini).json()
print(f"   {len(cards)} cards no deck")
assert len(cards) == 2
print("   OK\n")

print("5) ISOLAMENTO: intruso tenta ver os cards do deck do Vini (DEVE FALHAR)...")
r = client.get(f"/decks/{deck['id']}/cards", headers=outro)
print("   status:", r.status_code)
assert r.status_code == 404
print("   OK\n")

print("6) Editar um card...")
r = client.patch(f"/cards/{c1['id']}", json={"back": "Autenticacao multifator: 2+ fatores"}, headers=vini).json()
print("   novo verso:", r["back"])
assert "2+ fatores" in r["back"]
print("   OK\n")

print("7) Excluir o deck apaga os cards em cascata...")
client.delete(f"/decks/{deck['id']}", headers=vini)
r = client.get(f"/cards/{c1['id']}", headers=vini)
print("   buscar card apos excluir deck:", r.status_code)
assert r.status_code == 404
print("   OK — cascata funcionou\n")

print("=== TODOS OS TESTES DE DECKS E CARDS PASSARAM ===")
