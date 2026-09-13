"""
Fuso horário de quem fez a request, disponível em qualquer camada.

O projeto sempre calculou "hoje" no fuso de quem estuda -- streak,
crítico/hoje e elegibilidade de resposta usam `_hoje_no_fuso` (study.py),
alimentado pela dependência `get_user_timezone`. A cota diária de IA era a
exceção: comparava `last_reset_date != date.today()`, o relógio do
SERVIDOR. Em produção o servidor roda em UTC, então quem está no Brasil
via a cota renovar às 21h.

Por que um contextvar e não mais um parâmetro: o débito da cota acontece
lá no fundo, em `_chamar_ia` (services/ai.py), chamado por tutor_service e
error_explanation_service, chamados por três routers diferentes. Levar o
fuso até lá por parâmetro significaria mudar a assinatura de meia dúzia de
funções -- e obrigar um serviço de IA a saber que existe fuso horário, o
que ele não tem nada a ver.

O cabeçalho já vem em TODA request (api.js manda X-User-Timezone sempre),
então um middleware lê uma vez e deixa disponível. Cada request é uma task
própria, então não há vazamento entre usuários.

Sem cabeçalho, ou com valor que não bate com nenhum fuso IANA conhecido,
cai pra UTC -- mesma decisão (e mesmo motivo) da `get_user_timezone`:
clientes antigos, testes e chamadas diretas à API não mandam esse header,
e travar a request por causa disso seria pior.
"""
from contextvars import ContextVar
from datetime import date, datetime
from zoneinfo import ZoneInfo, available_timezones

# Calculado uma vez no import: available_timezones() varre a base de fusos
# do sistema operacional.
_VALIDOS = available_timezones()
UTC = ZoneInfo("UTC")

_fuso_da_request: ContextVar[ZoneInfo] = ContextVar("fuso_da_request", default=UTC)


def resolver(nome: str | None) -> ZoneInfo:
    """Nome IANA -> ZoneInfo, caindo pra UTC no que não for reconhecido."""
    if nome and nome in _VALIDOS:
        return ZoneInfo(nome)
    return UTC


def definir(nome: str | None) -> None:
    """Guarda o fuso desta request (chamado pelo middleware, em main.py)."""
    _fuso_da_request.set(resolver(nome))


def atual() -> ZoneInfo:
    """Fuso de quem fez a request atual, ou UTC."""
    return _fuso_da_request.get()


def hoje_local() -> date:
    """A data de HOJE para quem fez a request -- não pro servidor."""
    return datetime.now(atual()).date()
