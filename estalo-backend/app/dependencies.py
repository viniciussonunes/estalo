"""
A "catraca" do prédio.

get_current_user é a função que protege os endpoints. Ela:
1. Pega o crachá (token) que veio no cabeçalho da requisição
2. Lê quem é o usuário
3. Busca ele no banco
4. Se algo falhar, barra a entrada (erro 401)

Qualquer endpoint que quiser ser "só pra logado" é só pedir essa dependência.
"""
from zoneinfo import ZoneInfo, available_timezones

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import ler_token
from app.models import User

# Diz ao FastAPI: o crachá chega via login no endpoint /auth/login.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Calculado uma vez no import (não a cada request) — available_timezones()
# varre a base de fusos do sistema operacional.
_TIMEZONES_VALIDAS = available_timezones()


def get_user_timezone(
    x_user_timezone: str | None = Header(None, alias="X-User-Timezone"),
) -> ZoneInfo:
    """Fuso horário do usuário, mandado pelo frontend a cada request (ver
    api.js — Intl.DateTimeFormat().resolvedOptions().timeZone). Usado só
    pra calcular fronteiras de "dia" (streak, crítico/hoje, elegibilidade
    de resposta) — o armazenamento continua sempre UTC, isso nunca entra
    no banco.

    Sem header ou com valor que não bate com nenhum fuso IANA conhecido,
    cai pra UTC — mais seguro que travar a request (clientes antigos,
    testes automatizados e chamadas diretas à API não mandam esse header).
    """
    if x_user_timezone and x_user_timezone in _TIMEZONES_VALIDAS:
        return ZoneInfo(x_user_timezone)
    return ZoneInfo("UTC")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    erro = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Crachá inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    dados = ler_token(token)
    if dados is None:
        raise erro
    user_id, versao = dados

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None or user.token_version != versao:
        raise erro

    return user


def get_current_user_id(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> int:
    """Versão leve de get_current_user: só decodifica e valida o JWT, SEM
    consultar o banco. Use nos endpoints que só precisam do id pra filtrar
    queries (a grande maioria) — evita um SELECT redundante em toda
    request, já que o próprio token já é uma prova criptográfica válida da
    identidade.

    Deixou de ser 100% "sem consultar o banco" quando a troca de senha
    passou a derrubar sessões: agora lê UMA coluna (token_version) pra
    conferir se o crachá ainda é da geração vigente. Sem isso, "trocar a
    senha derruba as outras sessões" seria propaganda enganosa -- o token
    revogado continuaria abrindo todos os endpoints de estudo, que são
    justamente os que usam esta dependência. O custo é um SELECT de uma
    coluna por chave primária, numa request que já vai ao banco de
    qualquer jeito.

    Trade-off que continua de pé: se o usuário for excluído do banco, um
    token dele dentro da validade (7 dias) ainda passa por aqui -- a
    consulta devolve None e o token é recusado, então na prática isso
    também ficou coberto. Hoje não existe endpoint de exclusão de conta.

    Pra rotas que precisam dos dados de verdade do usuário (email, etc.),
    use get_current_user — ex: GET /auth/me.
    """
    erro = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Crachá inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    dados = ler_token(token)
    if dados is None:
        raise erro
    user_id, versao = dados

    atual = db.query(User.token_version).filter(User.id == int(user_id)).scalar()
    if atual is None or atual != versao:
        raise erro

    return int(user_id)


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Catraca extra pros endpoints de /admin/* (gestão de cotas).

    O pedido original dizia só "protegido por autenticação" -- mas isso
    sozinho deixaria QUALQUER usuário cadastrado listar e alterar a cota
    de todo mundo (GET /admin/users devolve dados de todos, PATCH altera
    o limite de qualquer user_id). Pra uma rota assim, "logado" não é
    proteção suficiente -- é preciso ser especificamente um admin.

    ADMIN_EMAILS (settings) é a lista de quem pode entrar, separada por
    vírgula; vazio por padrão (ninguém entra até configurar). Comparação
    é feita contra o email do token decodificado, não algo vindo do
    cliente -- não dá pra forjar.
    """
    if not eh_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito a administradores")
    return user


def eh_admin(user: User) -> bool:
    """Mesma regra da catraca acima, isolada porque o /auth/me também
    precisa dela -- o frontend não tinha como saber se deve mostrar o
    link do painel, e a rota /admin ficava acessível só por URL decorada.

    Continua sendo decidido no SERVIDOR, a partir do email do token: o
    campo que vai pro cliente é consequência, não fonte. Quem tentar
    forjar o `is_admin` na resposta esbarra na catraca do endpoint.
    """
    admins = {e.strip().lower() for e in settings.ADMIN_EMAILS.split(",") if e.strip()}
    return user.email.lower() in admins
