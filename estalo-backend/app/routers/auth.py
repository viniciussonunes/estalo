"""
Endpoints de autenticação: cadastro, login, "quem sou eu" e troca de senha.

Esses são os primeiros endpoints DE VERDADE do Estalo.
"""
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.dependencies import eh_admin, get_current_user
from app.models import User
from app.schemas.token import Token
from app.schemas.user import PasswordChange, QuotaOut, UserCreate, UserOut
from app.services import login_throttle, password_policy, quota_service

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def cadastrar(dados: UserCreate, db: Session = Depends(get_db)):
    """Cria um novo usuário com a senha já criptografada."""
    # Não deixa cadastrar email repetido.
    if db.query(User).filter(User.email == dados.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esse email já está cadastrado",
        )

    _exigir_senha_aceitavel(dados.password, dados.email)

    novo = User(
        email=dados.email,
        hashed_password=hash_password(dados.password),
    )
    db.add(novo)
    db.commit()
    db.refresh(novo)
    return novo


@router.post("/login", response_model=Token)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Confere email + senha e devolve o crachá (token).

    OAuth2PasswordRequestForm espera os campos 'username' e 'password'.
    Aqui o 'username' é o email do usuário.

    Erros seguidos bloqueiam a conta por um tempo crescente (429 +
    Retry-After) -- ver services/login_throttle.py pro porquê e pra escada.
    """
    user = db.query(User).filter(User.email == form.username).first()

    # Conta bloqueada nem chega a conferir a senha -- inclusive porque
    # verify_password é bcrypt, caro de propósito: responder cedo tira do
    # atacante o trabalho de CPU que ele estava tentando nos impor.
    if user:
        espera = login_throttle.segundos_de_bloqueio(user)
        if espera > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=login_throttle.mensagem_de_bloqueio(espera),
                headers={"Retry-After": str(espera)},
            )

    if not user or not verify_password(form.password, user.hashed_password):
        if user:
            espera = login_throttle.registrar_falha(user)
            db.commit()
            if espera > 0:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=login_throttle.mensagem_de_bloqueio(espera),
                    headers={"Retry-After": str(espera)},
                )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
        )

    # Acertou: zera a sequência de erros. Só grava se havia o que limpar,
    # pra um login comum não custar um UPDATE à toa.
    if user.failed_login_count or user.locked_until:
        login_throttle.registrar_sucesso(user)
        db.commit()

    token = create_access_token(subject=str(user.id), token_version=user.token_version)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def quem_sou_eu(user: User = Depends(get_current_user)):
    """Endpoint protegido: só responde se você mostrar um crachá válido."""
    return UserOut(
        id=user.id,
        email=user.email,
        created_at=user.created_at,
        is_admin=eh_admin(user),
    )


@router.get("/me/quota", response_model=QuotaOut)
def minha_cota(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Quanto de IA esta conta já usou hoje.

    Até aqui, o usuário comum não tinha como saber: existia só
    /admin/users, que lista todo mundo e exige ser admin. Ele descobria o
    limite BATENDO nele -- um modal aparecia no meio de um Tutor.

    Passa por reset_quotas_if_needed de propósito: sem isso a tela
    mostraria o consumo de ontem até a primeira chamada de IA do dia. Só
    zera o contador quando virou o dia; não consome nada.
    """
    quota = quota_service.reset_quotas_if_needed(user.id, db)
    return QuotaOut(
        consumido=quota.daily_tokens_consumed,
        limite=quota.daily_limit,
        restante=max(0, quota.daily_limit - quota.daily_tokens_consumed),
        renova_em=_proxima_virada(),
    )


def _proxima_virada() -> datetime:
    """Meia-noite seguinte no relógio do SERVIDOR -- que é onde o
    quota_service compara `last_reset_date != date.today()`.

    Em produção o servidor roda em UTC, então pra quem está no Brasil a
    cota renova às 21h locais, não à meia-noite. É uma inconsistência real
    com o resto do projeto (streak, "hoje" e elegibilidade usam o fuso de
    quem estuda, ver _hoje_no_fuso em study.py) -- mas mudar a REGRA de
    reset é outra tarefa. Aqui a escolha é contar a verdade: devolver o
    instante em que o contador de fato zera, pro frontend exibir no fuso
    de quem lê.
    """
    return datetime.combine(date.today() + timedelta(days=1), time.min)


def _exigir_senha_aceitavel(senha: str, email: str | None = None) -> None:
    """Aplica a regra de senha, traduzindo a recusa em 400 com frase pronta
    (ver services/password_policy.py sobre por que não é validação de
    schema do Pydantic)."""
    try:
        password_policy.validar(senha, email)
    except password_policy.SenhaFraca as fraca:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(fraca),
        ) from fraca


@router.post("/change-password", response_model=Token)
def trocar_senha(
    dados: PasswordChange,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Troca a senha de quem está logado.

    Antes disso não existia jeito NENHUM de trocar de senha -- quem tinha
    uma senha ruim (e o cadastro aceitava qualquer uma) estava preso a ela.

    Erros na senha atual contam no mesmo freio do login
    (services/login_throttle.py): o token já prova quem é, mas a senha
    atual é adivinhável do mesmo jeito, e um endpoint sem freio seria a
    porta dos fundos do que o /login fechou.
    """
    espera = login_throttle.segundos_de_bloqueio(user)
    if espera > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=login_throttle.mensagem_de_bloqueio(espera),
            headers={"Retry-After": str(espera)},
        )

    if not verify_password(dados.senha_atual, user.hashed_password):
        espera = login_throttle.registrar_falha(user)
        db.commit()
        if espera > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=login_throttle.mensagem_de_bloqueio(espera),
                headers={"Retry-After": str(espera)},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A senha atual está incorreta",
        )

    _exigir_senha_aceitavel(dados.senha_nova, user.email)

    if verify_password(dados.senha_nova, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A senha nova precisa ser diferente da atual",
        )

    user.hashed_password = hash_password(dados.senha_nova)
    # Trocar a senha com sucesso é retomada de controle da conta: limpa
    # qualquer sequência de erros pendente.
    login_throttle.registrar_sucesso(user)

    # Vira a geração dos crachás: todo token emitido antes desta linha
    # para de valer na hora (ver token_version em models/user.py). É o que
    # faz "troquei a senha" significar "quem estava dentro caiu" -- sem
    # isto, um aparelho perdido continuaria com a conta aberta por até 7
    # dias, e trocar a senha não adiantaria nada contra ele.
    user.token_version += 1
    db.commit()

    # Quem trocou a senha não pode ser vítima do próprio ato: devolve um
    # crachá novo, já na geração nova, pra a sessão ATUAL continuar. As
    # outras é que caem.
    return Token(access_token=create_access_token(
        subject=str(user.id), token_version=user.token_version,
    ))
