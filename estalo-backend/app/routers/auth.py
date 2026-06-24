"""
Endpoints de autenticação: cadastro, login e "quem sou eu".

Esses são os primeiros endpoints DE VERDADE do Estalo.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.dependencies import get_current_user
from app.models import User
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserOut

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
    """
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
        )

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def quem_sou_eu(user: User = Depends(get_current_user)):
    """Endpoint protegido: só responde se você mostrar um crachá válido."""
    return user
