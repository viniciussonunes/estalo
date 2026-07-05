"""Teste da arquitetura de fuso horário por usuário (Streak, heatmap, elegibilidade)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import ReviewHistory
from app.dependencies import get_user_timezone
from app.routers.study import _data_no_fuso, _hoje_no_fuso

client = TestClient(app)


def logar(email, senha="senha123"):
    client.post("/auth/register", json={"email": email, "password": senha})
    r = client.post("/auth/login", data={"username": email, "password": senha})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- 1) Unidade: helpers puros, sem depender do relógio da máquina ---
print("1) _data_no_fuso() converte corretamente um instante fixo pros dois fusos...")
# 2026-01-01 23:30 UTC -> já é 2026-01-02 em Tóquio (+9h), mas ainda é
# 2026-01-01 em Los Angeles (-8h em janeiro, sem DST).
instante = datetime(2026, 1, 1, 23, 30, 0)
tokyo = ZoneInfo("Asia/Tokyo")
la = ZoneInfo("America/Los_Angeles")
assert _data_no_fuso(instante, tokyo).isoformat() == "2026-01-02"
assert _data_no_fuso(instante, la).isoformat() == "2026-01-01"
print("   OK\n")

print("2) get_user_timezone() cai pra UTC sem header ou com valor inválido...")
assert get_user_timezone(None) == ZoneInfo("UTC")
assert get_user_timezone("Isso/NaoExiste") == ZoneInfo("UTC")
assert get_user_timezone("Asia/Tokyo") == ZoneInfo("Asia/Tokyo")
print("   OK\n")

# --- 2) Endpoint: heatmap agrupa o MESMO evento em dias diferentes conforme o fuso ---
print("3) heatmap-stats agrupa o mesmo evento em dias diferentes por fuso (endpoint real)...")
vini = logar("tz_vini@estalo.dev")
deck = client.post("/decks", json={"title": "Deck TZ"}, headers=vini).json()
card = client.post(f"/decks/{deck['id']}/cards", json={"front": "F", "back": "B"}, headers=vini).json()

# Responde uma vez pra criar o Review + 1 entrada em ReviewHistory, depois
# força o timestamp dessa entrada pra um instante de fronteira conhecido.
client.post(f"/study/cards/{card['id']}/answer", json={"quality": 4}, headers=vini)

instante_fronteira = datetime.utcnow().replace(hour=23, minute=30, second=0, microsecond=0)
db = SessionLocal()
h = db.query(ReviewHistory).filter(ReviewHistory.card_id == card["id"]).first()
h.avaliado_em = instante_fronteira
db.commit()
db.close()

utc_date = instante_fronteira.date().isoformat()
utc_date_mais_1 = (instante_fronteira.date() + timedelta(days=1)).isoformat()

heatmap_tokyo = client.get(
    "/study/heatmap-stats", headers={**vini, "X-User-Timezone": "Asia/Tokyo"}
).json()
heatmap_gmt12 = client.get(
    "/study/heatmap-stats", headers={**vini, "X-User-Timezone": "Etc/GMT+12"}
).json()
print("   heatmap (Tokyo):", heatmap_tokyo)
print("   heatmap (Etc/GMT+12):", heatmap_gmt12)

assert heatmap_tokyo.get(utc_date_mais_1) == 1, "Tóquio (+9h) deveria contar o evento no dia SEGUINTE ao UTC"
assert heatmap_gmt12.get(utc_date) == 1, "Etc/GMT+12 (-12h) deveria contar o evento no MESMO dia UTC"
assert utc_date not in heatmap_tokyo or heatmap_tokyo.get(utc_date, 0) == 0
print("   OK — o mesmo evento cai em dias de calendário diferentes conforme o fuso\n")

print("4) Sem header (ou header inválido) cai pra UTC -- comportamento antigo preservado...")
heatmap_sem_header = client.get("/study/heatmap-stats", headers=vini).json()
heatmap_invalido = client.get(
    "/study/heatmap-stats", headers={**vini, "X-User-Timezone": "lixo-invalido"}
).json()
assert heatmap_sem_header.get(utc_date) == 1
assert heatmap_invalido.get(utc_date) == 1
print("   OK\n")

# --- 3) Streak: sequência de dias com timestamps controlados, sem depender do relógio real ---
print("5) streak() conta sequência corretamente após o refactor (regressão, fuso UTC)...")
vini2 = logar("tz_streak@estalo.dev")
deck2 = client.post("/decks", json={"title": "Deck Streak"}, headers=vini2).json()
cards2 = [
    client.post(f"/decks/{deck2['id']}/cards", json={"front": f"F{i}", "back": f"B{i}"}, headers=vini2).json()
    for i in range(3)
]
db = SessionLocal()
hoje_utc = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
for i, c in enumerate(cards2):
    client.post(f"/study/cards/{c['id']}/answer", json={"quality": 4}, headers=vini2)
    h = db.query(ReviewHistory).filter(ReviewHistory.card_id == c["id"]).first()
    # 3 dias consecutivos terminando hoje, sempre ao meio-dia UTC (não
    # encosta em nenhuma fronteira de fuso plausível: -11h a +14h mantém
    # o mesmo dia de calendário em qualquer zona real).
    h.avaliado_em = hoje_utc - timedelta(days=2 - i)
    db.commit()
db.close()

streak_utc = client.get("/study/streak", headers=vini2).json()
streak_tokyo = client.get("/study/streak", headers={**vini2, "X-User-Timezone": "Asia/Tokyo"}).json()
print("   streak (UTC):", streak_utc)
print("   streak (Tokyo):", streak_tokyo)
assert streak_utc["longest_streak"] == 3 and streak_utc["current_streak"] == 3
assert streak_tokyo["longest_streak"] == 3 and streak_tokyo["current_streak"] == 3
print("   OK — 3 dias consecutivos contam certo independente do fuso (longe de fronteira)\n")

# --- 4) Elegibilidade / stats seguem funcionando com o fuso padrão (regressão) ---
print("6) /next e /decks/{id}/stats continuam funcionando normalmente (regressão básica)...")
vini3 = logar("tz_stats@estalo.dev")
deck3 = client.post("/decks", json={"title": "Deck Stats TZ"}, headers=vini3).json()
c3 = client.post(f"/decks/{deck3['id']}/cards", json={"front": "F", "back": "B"}, headers=vini3).json()

s = client.get(f"/study/decks/{deck3['id']}/stats", headers=vini3).json()
assert s["total_cards"] == 1 and s["new_cards"] == 1 and s["due_now"] == 1

prox = client.get(f"/study/decks/{deck3['id']}/next", headers=vini3).json()
assert prox["card_id"] == c3["id"]

r = client.post(f"/study/cards/{c3['id']}/answer", json={"quality": 1}, headers=vini3).json()
assert r["interval"] == 1 and r["repetitions"] == 0  # Crítico Imediato preservado
print("   OK\n")

print("Todos os testes de fuso horário passaram.")
