import os

try:
    from pydantic_settings import BaseSettings
except ImportError:
    # Fallback for older pydantic versions
    from pydantic import BaseSettings


class Settings(BaseSettings):
    # API настройки
    API_KEY: str = os.getenv("API_KEY", "your_secret_api_key_here")

    # Настройки Anthropic API
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "your_anthropic_api_key_here")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-7-sonnet-20250219")
    ANTHROPIC_MAX_TOKENS: int = int(os.getenv("ANTHROPIC_MAX_TOKENS", "32768"))

    # Пути к промптам
    PROMPTS_DIR: str = os.getenv("PROMPTS_DIR", "prompts")
    DEFAULT_PROMPT: str = os.getenv("DEFAULT_PROMPT", "ktru_detection.yaml")

    # Redis настройки
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # Настройки обработки задач
    TASK_MAX_ATTEMPTS: int = int(os.getenv("TASK_MAX_ATTEMPTS", "3"))
    TASK_POLL_INTERVAL: int = int(os.getenv("TASK_POLL_INTERVAL", "5"))

    # Настройки TTL для Redis
    TASK_PENDING_TTL: int = int(os.getenv("TASK_PENDING_TTL", str(7 * 24 * 60 * 60)))  # 7 дней
    TASK_COMPLETED_TTL: int = int(os.getenv("TASK_COMPLETED_TTL", str(3 * 24 * 60 * 60)))  # 3 дня
    TASK_FAILED_TTL: int = int(os.getenv("TASK_FAILED_TTL", str(14 * 24 * 60 * 60)))  # 14 дней

    # Таймауты
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "300"))

    # Настройки колбеков
    CALLBACK_URL: str = os.getenv("CALLBACK_URL", "http://localhost:8000/api/v1/callbacks/processing")
    CALLBACK_SECRET: str = os.getenv("CALLBACK_SECRET", "your_callback_secret_here")

    class Config:
        env_file = ".env"


settings = Settings()