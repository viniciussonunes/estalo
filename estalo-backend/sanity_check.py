"""
Teste de sanidade: monta a árvore de 4 níveis, cria deck/card/review
e roda o SM-2. Não é teste automatizado de verdade ainda — é só pra
você VER o esqueleto funcionando.
"""
from datetime import datetime

from app.core.database import Base, SessionLocal, engine
from app.models import Card, Deck, Folder, Review, User
from app.services.sm2 import SM2State, calcular_proxima_revisao

# Banco limpo a cada execução do teste.
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# 1) Usuário
vini = User(email="vini@estalo.dev", hashed_password="fake-hash")
db.add(vini)
db.commit()
db.refresh(vini)

# 2) Árvore de 4 níveis (sua dor #3)
n1 = Folder(name="Certificações Microsoft", owner_id=vini.id, depth=1)
db.add(n1); db.commit(); db.refresh(n1)
n2 = Folder(name="SC-900", owner_id=vini.id, parent_id=n1.id, depth=2)
db.add(n2); db.commit(); db.refresh(n2)
n3 = Folder(name="Identidade", owner_id=vini.id, parent_id=n2.id, depth=3)
db.add(n3); db.commit(); db.refresh(n3)
n4 = Folder(name="Autenticação", owner_id=vini.id, parent_id=n3.id, depth=4)
db.add(n4); db.commit(); db.refresh(n4)

# 3) Deck dentro do nível 4 + um card
deck = Deck(title="Métodos de MFA", owner_id=vini.id, folder_id=n4.id)
db.add(deck); db.commit(); db.refresh(deck)
card = Card(front="O que é MFA?",
            back="Autenticação multifator: 2+ fatores (algo que sabe/tem/é).",
            deck_id=deck.id, source="ai")
db.add(card); db.commit(); db.refresh(card)

# 4) Review inicial + uma rodada de SM-2 (você acertou de boa = nota 5)
review = Review(user_id=vini.id, card_id=card.id)
db.add(review); db.commit(); db.refresh(review)

estado = SM2State(review.ease_factor, review.interval, review.repetitions, review.due_date)
novo = calcular_proxima_revisao(estado, quality=5, hoje=datetime(2026, 6, 23))
review.ease_factor = novo.ease_factor
review.interval = novo.interval
review.repetitions = novo.repetitions
review.due_date = novo.due_date
review.last_reviewed = datetime(2026, 6, 23)
db.commit()

# --- Mostra o resultado: caminho da árvore + estado do SM-2 ---
def caminho(folder: Folder) -> str:
    partes = []
    atual = folder
    while atual:
        partes.append(atual.name)
        atual = atual.parent
    return " > ".join(reversed(partes))

print("Árvore (4 níveis):", caminho(n4))
print("Deck:", deck.title, "| Card:", card.front, f"(origem: {card.source})")
print("SM-2 após acerto nota 5:")
print(f"  intervalo = {review.interval} dia(s)")
print(f"  ease_factor = {review.ease_factor}")
print(f"  próxima revisão = {review.due_date.date()}")

db.close()
