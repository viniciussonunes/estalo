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
# Checa só os campos que essa regra de negócio valida (2 cards, ambos novos e
# ambos na fila de hoje) — comparar o dict inteiro quebra toda vez que um
# campo novo é adicionado ao StudyStats, mesmo sem mudar nenhum comportamento.
assert s["total_cards"] == 2 and s["due_now"] == 2 and s["new_cards"] == 2
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

print("5) Estudar o segundo card e ERRAR (nota 1) -> Crítico Imediato (due_date = agora)...")
prox2 = client.get(f"/study/decks/{did}/next", headers=vini).json()
print("   proximo card:", prox2["front"])
r = client.post(f"/study/cards/{prox2['card_id']}/answer", json={"quality": 1}, headers=vini).json()
print(f"   errou -> intervalo: {r['interval']} dia(s), repeticoes zeradas: {r['repetitions']}")
assert r["interval"] == 1 and r["repetitions"] == 0
print("   OK — card errado fica com interval=1 e repetitions=0\n")

print("6) Crítico Imediato (study.py:238-245): card errado reaparece NA HORA, sessão não encerra...")
prox3 = client.get(f"/study/decks/{did}/next", headers=vini).json()
print("   resposta:", prox3)
assert "concluida" not in prox3, f"sessão não deveria estar marcada como concluída: {prox3}"
assert prox3["card_id"] == prox2["card_id"], "o card errado (crítico) deveria reaparecer imediatamente"
print("   OK — comportamento de 'Crítico Imediato' confirmado, card disponível de novo na hora\n")

print("7) Com TODOS os cards dominados (repetitions>=2) e due_date no futuro, /next encerra a sessão...")
# Simula o estado de "dominado, nada pendente" direto no banco — chegar lá
# via respostas reais exigiria burlar a trava de elegibilidade (mesmo card
# não pode ser respondido 2x no mesmo dia sem ignorar_elegibilidade). O que
# este teste valida é o CONTRATO do endpoint dado esse estado, não a
# progressão do SM-2 em si (isso é coberto pelos testes de interval/reps
# acima).
db = SessionLocal()
for cid in (c1["id"], c2["id"]):
    rev = db.query(Review).filter(Review.card_id == cid).first()
    rev.repetitions = 2
    rev.due_date = datetime.utcnow() + timedelta(days=5)
    db.add(rev)
db.commit()
db.close()
prox4 = client.get(f"/study/decks/{did}/next", headers=vini).json()
print("   resposta:", prox4)
assert prox4.get("concluida") is True and prox4["motivo"] == "sem_cards"
print("   OK — SessaoConcluida devolvida corretamente quando não há cards pendentes\n")

print("8) Simular passagem do tempo: forco um card a vencer de novo e ele reaparece...")
db = SessionLocal()
rev = db.query(Review).filter(Review.card_id == prox2["card_id"]).first()
rev.due_date = datetime.utcnow() - timedelta(days=2)  # finge que ja venceu
db.commit()
db.close()
prox5 = client.get(f"/study/decks/{did}/next", headers=vini).json()
print("   card que reapareceu:", prox5.get("front"))
assert "concluida" not in prox5 and prox5["card_id"] == prox2["card_id"]
print("   OK — card vencido voltou pra fila\n")

print("=== TODOS OS TESTES DE ESTUDO PASSARAM ===")
