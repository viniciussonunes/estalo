"""
Configuração central do app.

Pensa nesse arquivo como o painel de controle do prédio: tudo que muda
entre o seu computador e o servidor de produção (URL do banco, chave secreta)
fica aqui, lido a partir de variáveis de ambiente (.env).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Por padrão usa SQLite (um arquivo local) pra você rodar AGORA, sem instalar
    # nada. Em produção, troque pela URL do PostgreSQL no arquivo .env.
    DATABASE_URL: str = "sqlite:///./estalo.db"

    # Chave usada pra assinar os tokens JWT. NUNCA suba a real pro GitHub.
    SECRET_KEY: str = "troque-isso-em-producao"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Profundidade máxima da árvore de pastas (sua dor #3: 4 níveis).
    MAX_FOLDER_DEPTH: int = 4

    # Chave da API do Gemini (gerar cards com IA). Fica vazia por padrão;
    # você preenche no arquivo .env. NUNCA suba a chave real pro GitHub.
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-flash-latest"


settings = Settings()
