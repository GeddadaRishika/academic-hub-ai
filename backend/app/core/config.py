from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://academic:academic@localhost:5432/academic_hub"
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-3.8-flas"
    gemini_embed_model: str = "gemini-embedding-001"
    jwt_secret_key: str = "development-only-change-me"
    access_token_expire_minutes: int = 1440
    upload_dir: str = "./uploads"
    max_upload_mb: int = 20
    cors_origins: str = "http://localhost:5173"
    demo_admin_email: str = "admin@academichub.local"
    demo_admin_password: str = "AdminDemo123!"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self):
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

settings = Settings()
