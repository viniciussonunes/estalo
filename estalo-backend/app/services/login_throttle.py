"""
Freio de força bruta no login.

Por que existe: até aqui, `/auth/login` aceitava tentativas ilimitadas. Some
isso ao fato de o cadastro aceitar QUALQUER senha (inclusive de um
caractere) e de não existir troca de senha — quem entrou com senha fraca
está preso a ela — e adivinhar a senha de uma conta era questão de rodar um
laço. Este módulo é a defesa que protege inclusive as contas que já existem,
sem exigir nada do usuário.

Escolhas, e o que elas custam:

* **Conta por conta, não por IP.** O contador mora em duas colunas de
  `users`. Um contador por IP pegaria também o ataque distribuído, mas
  exigiria tabela própria e, em serverless atrás de CDN, o IP chega por
  cabeçalho — dá pra forjar. Travar a conta protege exatamente o que se quer
  proteger: aquela senha.
* **Escada, não paredão.** Cinco erros seguidos custam 1 minuto; a próxima
  rodada, 5; daí em diante, 15. Quem errou de verdade espera um minuto e
  segue a vida; quem está adivinhando bate em paredes cada vez maiores. Um
  bloqueio fixo e longo puniria igual os dois, e sem "esqueci minha senha"
  no app um bloqueio longo é assustador de verdade.
* **Acertar zera tudo.** O contador é de erros CONSECUTIVOS.

Limitação conhecida: email que não existe não é contado (não há linha pra
contar). Isso não abre a conta de ninguém — não há o que adivinhar — mas
significa que o bloqueio revela que aquele email tem conta. Esse vazamento
já existia de qualquer forma: o cadastro responde "Esse email já está
cadastrado".
"""
from datetime import datetime, timedelta, timezone

from app.models import User

# Quantos erros seguidos até o primeiro bloqueio.
ERROS_ATE_BLOQUEAR = 5

# Duração de cada bloqueio, em ordem. Depois do último, repete o último.
ESCADA_DE_BLOQUEIO = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
)


def agora_utc() -> datetime:
    """Naive-UTC, a convenção de toda coluna DateTime do projeto (mesma
    razão explicada em routers/study.py)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def segundos_de_bloqueio(user: User, agora: datetime | None = None) -> int:
    """Quantos segundos ainda faltam do bloqueio. 0 = pode tentar."""
    if user.locked_until is None:
        return 0
    agora = agora or agora_utc()
    restante = (user.locked_until - agora).total_seconds()
    return max(0, int(restante + 0.999))  # arredonda pra cima: 0.2s ainda é bloqueio


def registrar_falha(user: User, agora: datetime | None = None) -> int:
    """Contabiliza uma senha errada. Devolve os segundos de bloqueio
    resultantes (0 se ainda não bloqueou).

    Não faz commit: quem chama decide a hora de gravar.
    """
    agora = agora or agora_utc()
    user.failed_login_count = (user.failed_login_count or 0) + 1

    # Bloqueia a cada RODADA fechada de erros, não em toda falha depois da
    # quinta: passado o primeiro bloqueio, a pessoa ganha cinco tentativas
    # novas antes do próximo. (Sem o resto zero aqui, o 6º erro já
    # bloquearia de novo e a escada nunca subiria de degrau.)
    if user.failed_login_count % ERROS_ATE_BLOQUEAR != 0:
        return 0

    # Rodadas fechadas até agora definem o degrau: 5 erros -> degrau 0
    # (1 min); 10 -> degrau 1 (5 min); 15 -> degrau 2 (15 min).
    degrau = user.failed_login_count // ERROS_ATE_BLOQUEAR - 1
    duracao = ESCADA_DE_BLOQUEIO[min(degrau, len(ESCADA_DE_BLOQUEIO) - 1)]
    user.locked_until = agora + duracao
    return int(duracao.total_seconds())


def registrar_sucesso(user: User) -> None:
    """Login certo limpa o histórico de erros. Sem commit, igual acima."""
    user.failed_login_count = 0
    user.locked_until = None


def mensagem_de_bloqueio(segundos: int) -> str:
    """Texto pro usuário. Fala em minutos quando passa de um minuto —
    'tente de novo em 847 segundos' não ajuda ninguém."""
    if segundos > 60:
        minutos = (segundos + 59) // 60
        return (
            f"Muitas tentativas seguidas. Tente de novo em {minutos} minutos."
        )
    return "Muitas tentativas seguidas. Tente de novo em cerca de 1 minuto."
