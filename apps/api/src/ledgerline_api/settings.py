from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://ledgerline:ledgerline@localhost:5434/ledgerline"
    upload_dir: Path = Path("data/uploads")
    # Signs pagination cursors so clients can't forge or edit them. Override in every real deployment.
    cursor_secret: str = "dev-only-cursor-secret"
    # Extraction is synchronous until slice 3, so a request is capped at ~4 minutes of model time.
    max_files_per_request: int = 10
    idempotency_ttl_hours: int = 24
    # An in-progress key older than this is treated as abandoned (the server died mid-request).
    idempotency_lock_timeout_s: int = 900

    # Ollama runs natively on the host: Docker on macOS has no GPU access. See docs/adr/0001.
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "gemma4:12b"
    llm_temperature: float = 0.0
    # Always sent explicitly: Ollama's default context is small and truncates long prompts silently.
    llm_num_ctx: int = 8192
    llm_keep_alive: str = "10m"
    llm_timeout_s: float = 180.0


settings = Settings()
