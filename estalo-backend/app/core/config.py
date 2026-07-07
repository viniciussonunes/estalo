from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco — SQLite local por padrão; PostgreSQL em produção via DATABASE_URL
    DATABASE_URL: str = "sqlite:///./estalo.db"

    # Connection string alternativa, apontando pro endpoint *pooled* (PgBouncer)
    # do Neon (host com "-pooler"). Se setada, tem prioridade sobre DATABASE_URL —
    # ver app/core/database.py. Deixe vazia pra manter o comportamento atual.
    # Confirmado em 2026-07-03 que a DATABASE_URL provisionada pela integração
    # Neon×Vercel já é pooled por padrão — essa variável fica como porta de
    # emergência (custo zero) caso isso mude ou seja preciso trocar de host.
    DATABASE_URL_POOL: str = ""

    # JWT
    SECRET_KEY: str = "troque-isso-em-producao"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 dias

    # Pastas
    MAX_FOLDER_DEPTH: int = 4

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # CORS — URL do frontend em produção (Vercel).
    # Localmente a origem http://localhost:5173 é sempre permitida.
    FRONTEND_URL: str = ""

    # Admin — emails com acesso a /admin/* (gestão de cotas), separados por
    # vírgula. Vazio por padrão = ninguém entra (não existe "admin de
    # fábrica"). Decisão consciente: nada no pedido original especificava
    # QUEM pode acessar /admin, e "protegido por autenticação" sozinho
    # deixaria qualquer usuário cadastrado ver e alterar a cota de todo
    # mundo -- ver comentário em app/dependencies.py/require_admin.
    ADMIN_EMAILS: str = ""

    # Observabilidade — Sentry (ver app/main.py). Vazio por padrão = SDK
    # desabilitado, mesmo padrão do frontend (src/sentry.js): dá pra rodar
    # local/CI sem precisar de conta no Sentry nem de mockar nada.
    SENTRY_DSN: str = ""


settings = Settings()
