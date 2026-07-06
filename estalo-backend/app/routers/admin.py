"""
Endpoints administrativos: gestão de cota de tokens de IA por usuário.

Protegidos por require_admin (app/dependencies.py) -- não é só "logado",
é especificamente quem está em settings.ADMIN_EMAILS. Ver o comentário lá
sobre por que "protegido por autenticação" sozinho não seria suficiente
pra uma rota que lista e altera dados de TODOS os usuários.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import require_admin
from app.models import User
from app.models.user_quota import DEFAULT_DAILY_LIMIT, UserQuota
from app.schemas.admin import AdminUserOut, UpdateLimitRequest
from app.services.quota_service import reset_quotas_if_needed

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/users", response_model=list[AdminUserOut])
def listar_usuarios(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Lista todos os usuários com consumo/limite de tokens de IA.

    LEFT JOIN com user_quotas: um usuário que nunca chamou IA ainda não
    tem linha lá (só é criada no primeiro uso, ver quota_service) -- aqui
    ele aparece com os defaults (0 consumido, limite padrão), sem forçar
    a criação da linha só por causa desta listagem.
    """
    linhas = (
        db.query(User, UserQuota)
        .outerjoin(UserQuota, UserQuota.user_id == User.id)
        .order_by(User.id)
        .all()
    )
    return [
        AdminUserOut(
            user_id=user.id,
            email=user.email,
            daily_tokens_consumed=quota.daily_tokens_consumed if quota else 0,
            daily_limit=quota.daily_limit if quota else DEFAULT_DAILY_LIMIT,
        )
        for user, quota in linhas
    ]


@router.patch("/users/{user_id}/limit", response_model=AdminUserOut)
def atualizar_limite(
    user_id: int,
    dados: UpdateLimitRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Atualiza o limite diário de tokens de um usuário específico.

    Reaproveita reset_quotas_if_needed (quota_service) pra criar a linha
    de cota se ainda não existir, em vez de duplicar essa lógica de
    get-or-create aqui.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")

    quota = reset_quotas_if_needed(user_id, db)
    quota.daily_limit = dados.daily_limit
    db.commit()

    return AdminUserOut(
        user_id=user.id,
        email=user.email,
        daily_tokens_consumed=quota.daily_tokens_consumed,
        daily_limit=quota.daily_limit,
    )
