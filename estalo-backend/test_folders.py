"""Teste de ponta a ponta do CRUD de pastas: árvore, trava de 4 níveis e isolamento entre usuários."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def criar_usuario_e_logar(email, senha="senha123"):
    client.post("/auth/register", json={"email": email, "password": senha})
    r = client.post("/auth/login", data={"username": email, "password": senha})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

print("Preparando dois usuários...")
vini = criar_usuario_e_logar("vini@estalo.dev")
outro = criar_usuario_e_logar("intruso@estalo.dev")
print("OK\n")

print("1) Montando a árvore de 4 níveis (usuário Vini)...")
n1 = client.post("/folders", json={"name": "Certificacoes Microsoft"}, headers=vini).json()
n2 = client.post("/folders", json={"name": "SC-900", "parent_id": n1["id"]}, headers=vini).json()
n3 = client.post("/folders", json={"name": "Identidade", "parent_id": n2["id"]}, headers=vini).json()
n4 = client.post("/folders", json={"name": "Autenticacao", "parent_id": n3["id"]}, headers=vini).json()
print(f"   niveis: {n1['depth']} -> {n2['depth']} -> {n3['depth']} -> {n4['depth']}")
assert [n1["depth"], n2["depth"], n3["depth"], n4["depth"]] == [1, 2, 3, 4]
print("   OK — 4 niveis criados com profundidade correta\n")

print("2) Tentando criar um 5o nivel (DEVE FALHAR)...")
r = client.post("/folders", json={"name": "Nivel 5", "parent_id": n4["id"]}, headers=vini)
print("   status:", r.status_code, "| detalhe:", r.json().get("detail"))
assert r.status_code == 400
print("   OK — a trava dos 4 niveis funcionou\n")

print("3) Listando a arvore do Vini...")
arvore = client.get("/folders", headers=vini).json()
caminho = arvore[0]["name"] + " > " + arvore[0]["children"][0]["name"] + " > " + \
          arvore[0]["children"][0]["children"][0]["name"] + " > " + \
          arvore[0]["children"][0]["children"][0]["children"][0]["name"]
print("   arvore:", caminho)
assert caminho == "Certificacoes Microsoft > SC-900 > Identidade > Autenticacao"
print("   OK — arvore montada certinha pelo Pydantic\n")

print("4) ISOLAMENTO: o intruso ve as pastas dele (vazia)...")
arvore_intruso = client.get("/folders", headers=outro).json()
print("   pastas do intruso:", arvore_intruso)
assert arvore_intruso == []
print("   OK — intruso nao ve as pastas do Vini\n")

print("5) ISOLAMENTO: intruso tenta acessar pasta do Vini (DEVE FALHAR)...")
r = client.get(f"/folders/{n1['id']}", headers=outro)
print("   status:", r.status_code, "| detalhe:", r.json().get("detail"))
assert r.status_code == 404
print("   OK — pasta de outro usuario aparece como 'nao encontrada'\n")

print("6) ISOLAMENTO: intruso tenta criar subpasta dentro da pasta do Vini (DEVE FALHAR)...")
r = client.post("/folders", json={"name": "invasao", "parent_id": n1["id"]}, headers=outro)
print("   status:", r.status_code)
assert r.status_code == 404
print("   OK — nao da pra pendurar pasta na arvore alheia\n")

print("7) Excluir pasta raiz apaga tudo em cascata...")
client.delete(f"/folders/{n1['id']}", headers=vini)
arvore = client.get("/folders", headers=vini).json()
print("   arvore do Vini apos exclusao:", arvore)
assert arvore == []
print("   OK — cascata funcionou\n")

print("=== TODOS OS TESTES DE PASTAS PASSARAM ===")
