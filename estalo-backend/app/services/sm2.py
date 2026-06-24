"""
Algoritmo SM-2 — o cérebro da repetição espaçada.

A ideia é simples e poderosa: card que você acerta com facilidade volta cada
vez mais espaçado (3 dias, 7 dias, 16 dias...). Card que você erra volta JÁ.
Assim você gasta tempo só no que ainda não dominou — o oposto do Quizlet,
que te faz revisar tudo igual.

Como funciona a nota (quality), de 0 a 5:
    0-2 = errou / não lembrou  → reseta o progresso, card volta amanhã
    3   = acertou com dificuldade
    4   = acertou
    5   = acertou de boa, instantâneo

Esta função é "pura": recebe o estado atual e a nota, devolve o estado novo.
Ela não toca no banco — quem salva é o service. Isso facilita testar.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class SM2State:
    ease_factor: float
    interval: int
    repetitions: int
    due_date: datetime


def calcular_proxima_revisao(estado: SM2State, quality: int, hoje: datetime | None = None) -> SM2State:
    if not 0 <= quality <= 5:
        raise ValueError("quality precisa estar entre 0 e 5")

    hoje = hoje or datetime.utcnow()
    ease = estado.ease_factor
    interval = estado.interval
    reps = estado.repetitions

    if quality < 3:
        # Errou: zera as repetições e o card volta amanhã.
        reps = 0
        interval = 1
    else:
        # Acertou: avança o intervalo.
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = round(interval * ease)
        reps += 1

    # Ajusta o "fator de facilidade" conforme o desempenho.
    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(1.3, ease)  # nunca deixa cair abaixo de 1.3

    return SM2State(
        ease_factor=round(ease, 2),
        interval=interval,
        repetitions=reps,
        due_date=hoje + timedelta(days=interval),
    )
