from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://ledgerline:ledgerline@localhost:5434/ledgerline"

    # Uploaded PDFs live in S3-compatible storage (SeaweedFS locally) so the API and workers can run apart.
    s3_endpoint_url: str = "http://localhost:8333"
    s3_bucket: str = "invoices"
    s3_access_key: str = "ledgerline"
    s3_secret_key: str = "ledgerline-secret"

    broker_url: str = "amqp://ledgerline:ledgerline@localhost:5672//"
    rabbitmq_management_url: str = "http://ledgerline:ledgerline@localhost:15672"
    redis_url: str = "redis://localhost:6379/0"

    # Backpressure: uploads get 429 once this many extraction jobs are waiting.
    max_queue_depth: int = 500
    upload_retry_after_s: int = 30

    # Model calls in flight across all workers. Match Ollama's OLLAMA_NUM_PARALLEL; more just queue inside it.
    llm_max_concurrency: int = 1
    # Slots are leased and renewed every lease/3 while the call runs; a killed worker's slot frees itself
    # after at most one lease.
    llm_slot_lease_s: int = 30
    llm_slot_wait_s: int = 600

    # An extraction attempt holds a lease it renews while working; a killed worker's lease lapses quickly.
    extraction_lease_s: int = 60
    extraction_heartbeat_s: int = 20
    extraction_max_retries: int = 5
    extraction_retry_backoff_base_s: float = 2.0
    extraction_retry_backoff_max_s: int = 300
    # Signs pagination cursors so clients can't forge or edit them. Override in every real deployment.
    cursor_secret: str = "dev-only-cursor-secret"
    # Extraction is queued, so the cap only bounds request size (50 PDFs), not model time.
    max_files_per_request: int = 50
    idempotency_ttl_hours: int = 24
    # An in-progress key older than this is treated as abandoned (the server died mid-request).
    idempotency_lock_timeout_s: int = 900

    # Ollama runs natively on the host: Docker on macOS has no GPU access. See docs/adr/0001.
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "gemma4:12b"
    llm_temperature: float = 0.0
    # Always sent explicitly: Ollama's default context is small and truncates long prompts silently.
    llm_num_ctx: int = 8192
    # Ollama truncates an over-long prompt silently (measured: a ~9.7k-token prompt with num_ctx 8192 came back
    # as 4,099 prompt tokens) and has no tokenizer endpoint, so prompts are budgeted client-side.
    llm_output_reserve_tokens: int = 2048
    llm_keep_alive: str = "10m"
    llm_timeout_s: float = 180.0

    # The ERP that purchase orders and goods receipts come from (apps/erp_mock locally). Beat runs sync_erp
    # every interval; a run that finds the previous one still going skips.
    erp_base_url: str = "http://localhost:8100"
    erp_sync_interval_s: int = 300
    erp_page_size: int = 100
    erp_timeout_s: float = 30.0
    # 429s in a row before a sync run gives up (the next run resumes from the saved cursor), and the longest
    # Retry-After honoured.
    erp_max_rate_limited: int = 10
    erp_retry_after_cap_s: int = 60
    # 3-way match: an invoice unit price may differ from the PO price by this much.
    match_price_tolerance_pct: Decimal = Decimal("1")

    # Exception agent: at most this many model responses that ask for tools, and this long per run (counted
    # from when it gets the model, not while it waits for a slot). Over either, it proposes a hold.
    agent_max_turns: int = 8
    agent_wall_clock_s: float = 90.0


settings = Settings()
