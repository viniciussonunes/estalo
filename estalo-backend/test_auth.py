"""Teste de ponta a ponta da autenticação usando o cliente de teste do FastAPI."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

print("1) Cadastro de usuário...")
r = client.post("/auth/register", json={"email": "vini@estalo.dev", "password": "senha123"})
print("   status:", r.status_code, "| resposta:", r.json())
assert r.status_code == 201
assert "hashed_password" not in r.json()  # senha NUNCA volta
print("   OK — usuário criado e senha não vazou\n")

print("2) Cadastro duplicado (deve falhar)...")
r = client.post("/auth/register", json={"email": "vini@estalo.dev", "password": "outra"})
print("   status:", r.status_code, "| resposta:", r.json())
assert r.status_code == 400
print("   OK — barrou email repetido\n")

print("3) Login com senha errada (deve falhar)...")
r = client.post("/auth/login", data={"username": "vini@estalo.dev", "password": "errada"})
print("   status:", r.status_code)
assert r.status_code == 401
print("   OK — barrou senha errada\n")

print("4) Login correto...")
r = client.post("/auth/login", data={"username": "vini@estalo.dev", "password": "senha123"})
print("   status:", r.status_code)
token = r.json()["access_token"]
print("   token (início):", token[:25], "...")
assert r.status_code == 200
print("   OK — crachá emitido\n")

print("5) Acessar /me SEM crachá (deve falhar)...")
r = client.get("/auth/me")
print("   status:", r.status_code)
assert r.status_code == 401
print("   OK — catraca barrou quem não tem crachá\n")

print("6) Acessar /me COM crachá...")
r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
print("   status:", r.status_code, "| resposta:", r.json())
assert r.status_code == 200
assert r.json()["email"] == "vini@estalo.dev"
print("   OK — entrou com crachá válido\n")

print("=== TODOS OS TESTES PASSARAM ===")
