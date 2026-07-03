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


settings = Settings()
