from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Discord Configuration
    DISCORD_BOT_TOKEN: str = ""
    DISCORD_CLIENT_ID: str = ""
    DISCORD_GUILD_ID: int | None = None

    # Database Configuration
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/dgg_pm"

    # Outbox Worker Configuration
    OUTBOX_POLL_INTERVAL_SECONDS: float = 5.0
    OUTBOX_BATCH_SIZE: int = 10

    # API / Health Server Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DEBUG: bool = False


settings = Settings()
