"""
Quota Manager — controla consumo diário de tokens de IA por usuário, pra
uma conta sozinha não estourar a cota compartilhada da chave do Gemini
(ver app/models/user_quota.py pro motivo concreto).

A estimativa de tokens usada por quem chama check_and_consume_tokens é
grosseira de propósito (caracteres/4, ver _estimar_tokens em ai.py) — o
objetivo não é contar exato (isso exigiria o tokenizer real do modelo), e
sim ter um teto que barre ANTES de gastar cota numa chamada.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models.user_quota import UserQuota

# QuotaExceededError mora em app/services/ai.py (não aqui) -- é lá que
# _chamar_gemini a levanta quando check_and_consume_tokens devolve False.
# Deixá-la em ai.py evita import circular (ai.py já importa deste módulo)
# e permite que ela subclasse IAError, reaproveitando o `except IAError`
# que os routers já têm, sem precisar mexer em cada endpoint.


def _buscar_ou_criar(user_id: int, db: Session) -> UserQuota:
    quota = db.get(UserQuota, user_id)
    if quota is None:
        quota = UserQuota(user_id=user_id)
        db.add(quota)
        db.flush()
    return quota


def reset_quotas_if_needed(user_id: int, db: Session) -> UserQuota:
    """Zera daily_tokens_consumed se last_reset_date não é hoje.

    Assinatura pedida originalmente era reset_quotas_if_needed(user_id),
    sem `db` -- sem uma sessão não dá pra consultar nem persistir nada,
    então o parâmetro foi acrescentado (mesmo ajuste já feito antes em
    get_all_deck_ids_in_folder, por motivo idêntico).
    """
    quota = _buscar_ou_criar(user_id, db)
    hoje = date.today()
    if quota.last_reset_date != hoje:
        quota.daily_tokens_consumed = 0
        quota.last_reset_date = hoje
    db.commit()
    return quota


def check_and_consume_tokens(user_id: int, estimated_tokens: int, db: Session) -> bool:
    """Se o usuário ainda tem cota hoje, já debita estimated_tokens e
    retorna True. Se não tem, retorna False SEM debitar nada -- a chamada
    que motivou a estimativa não deve ser feita (ver ai.py/_chamar_gemini).
    """
    quota = reset_quotas_if_needed(user_id, db)
    if quota.daily_tokens_consumed + estimated_tokens > quota.daily_limit:
        return False
    quota.daily_tokens_consumed += estimated_tokens
    db.commit()
    return True
