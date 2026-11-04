"""Application settings.

All configuration comes from the repository-root ``.env`` file (or real environment
variables, which always win). The same keys are used locally and on Cloud Run; the
deploy script only swaps values for production-specific ones (see deploy/scripts/).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV_FILE, ".env"),
        extra="ignore",  # the root .env also holds UI_* keys read by the frontend
    )

    # --- Runtime -----------------------------------------------------------
    app_env: Literal["local", "staging", "production"] = "local"
    app_name: str = "AgentOS"
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    cors_origins: str = "http://localhost:5173"

    # --- Authentication ----------------------------------------------------
    # dev    -> trusts the X-Dev-User header (local only, refused in production)
    # google -> verifies Google ID tokens sent as "Authorization: Bearer <token>"
    auth_mode: Literal["dev", "google"] = "dev"
    dev_user_email: str = "dev@example.com"
    google_client_id: str = ""
    allowed_email_domains: str = ""  # comma separated, empty = any verified Google account
    admin_emails: str = ""  # comma separated; always admins, even if the users table says otherwise
    # Role for people who are not in the users table yet.
    default_user_role: Literal["platform_user", "platform_admin"] = "platform_user"

    @field_validator("default_user_role", mode="before")
    @classmethod
    def _legacy_role_names(cls, value: object) -> object:
        # Older .env files say builder or viewer (platform_user) or admin (platform_admin).
        renamed = {"builder": "platform_user", "viewer": "platform_user", "admin": "platform_admin"}
        return renamed.get(value, value) if isinstance(value, str) else value

    # --- Database (Cloud SQL for PostgreSQL + pgvector) ---------------------
    database_url: str = "postgresql+asyncpg://agentflow:agentflow@localhost:5432/agentflow"
    db_auto_create: bool = True  # create tables on startup; use Alembic for real migrations
    db_pool_size: int = 5

    # --- Cache / rate limiting (Memorystore for Redis) ----------------------
    redis_url: str = ""  # empty disables rate limiting
    rate_limit_runs_per_minute: int = 30

    # --- LLM and embeddings (Vertex AI Agent Platform) ----------------------
    # mock   -> deterministic offline model (local development and tests)
    # gemini -> Gemini models through google-genai (api_key or vertex backend)
    # claude -> Claude on Vertex AI (requires GCP_PROJECT_ID)
    llm_provider: Literal["mock", "gemini", "claude"] = "mock"
    genai_backend: Literal["api_key", "vertex"] = "api_key"
    gemini_api_key: SecretStr | None = None
    gcp_project_id: str = ""
    gcp_location: str = "us-central1"
    gemini_model: str = "gemini-2.5-flash"
    claude_model: str = "claude-sonnet-5-5"
    embedding_model: str = "text-embedding-005"
    embedding_dim: int = 768
    llm_max_output_tokens: int = 1024

    # --- Object storage (Cloud Storage) -------------------------------------
    storage_backend: Literal["local", "gcs"] = "local"
    local_storage_dir: str = "./data/storage"
    gcs_bucket: str = ""

    # --- Run dispatch (Cloud Tasks) -----------------------------------------
    # inline      -> run in a background task inside this process (local dev)
    # cloud_tasks -> enqueue an HTTP task that calls /internal/runs/{id}/execute
    task_backend: Literal["inline", "cloud_tasks"] = "inline"
    cloud_tasks_queue: str = "agentflow-runs"
    cloud_tasks_location: str = "us-central1"
    cloud_tasks_invoker_sa: str = ""
    # local: fake endpoint for development. gcp: Cloud Build + Cloud Run / Agent Engine.
    deploy_backend: Literal["local", "gcp"] = "local"
    # Artifact Registry repo that holds agent images (Cloud Run deployments).
    gcp_artifact_repo: str = "agentflow"
    # The one service account every deployed agent runs as. Grant it only what agents need.
    agent_runtime_service_account: str = ""
    # Agent Gateway: full template name, projects/PROJECT/locations/REGION/templates/NAME.
    # The region is read from the name. Required in production (prompts are screened or refused).
    model_armor_template: str = ""
    backend_public_url: str = "http://localhost:8080"

    # --- Guardrails ----------------------------------------------------------
    pii_redaction_enabled: bool = True

    # --- Observability -------------------------------------------------------
    otel_enabled: bool = False
    otel_exporter: Literal["console", "gcp", "otlp"] = "console"
    # Collector for OTEL_EXPORTER=otlp, for example this server's own /v1/traces.
    otel_otlp_endpoint: str = ""

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        # "GEMINI_API_KEY=" in .env means unset, not an empty key.
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        errors: list[str] = []

        if self.app_env == "production":
            if self.auth_mode != "google":
                errors.append("production requires AUTH_MODE=google")
            if self.llm_provider == "mock":
                errors.append("production requires LLM_PROVIDER=gemini or claude")
            if "*" in self.cors_origin_list:
                errors.append("production CORS_ORIGINS must list explicit origins")

        if self.auth_mode == "google" and not self.google_client_id:
            errors.append("AUTH_MODE=google requires GOOGLE_CLIENT_ID")

        if self.llm_provider != "mock":
            if self.genai_backend == "api_key" and self.gemini_api_key is None:
                errors.append("GEMINI_API_KEY is required when GENAI_BACKEND=api_key")
            needs_vertex = self.genai_backend == "vertex" or self.llm_provider == "claude"
            if needs_vertex and not self.gcp_project_id:
                errors.append("GCP_PROJECT_ID is required for Vertex AI / Claude")

        if self.storage_backend == "gcs" and not self.gcs_bucket:
            errors.append("STORAGE_BACKEND=gcs requires GCS_BUCKET")

        if self.task_backend == "cloud_tasks":
            if not self.gcp_project_id:
                errors.append("TASK_BACKEND=cloud_tasks requires GCP_PROJECT_ID")
            if not self.cloud_tasks_invoker_sa:
                errors.append("TASK_BACKEND=cloud_tasks requires CLOUD_TASKS_INVOKER_SA")

        if self.otel_enabled and self.otel_exporter == "otlp" and not self.otel_otlp_endpoint:
            errors.append("OTEL_EXPORTER=otlp requires OTEL_OTLP_ENDPOINT")

        if self.deploy_backend == "gcp":
            for key, value in (
                ("GCP_PROJECT_ID", self.gcp_project_id),
                ("GCS_BUCKET", self.gcs_bucket),
                ("AGENT_RUNTIME_SERVICE_ACCOUNT", self.agent_runtime_service_account),
            ):
                if not value:
                    errors.append(f"DEPLOY_BACKEND=gcp requires {key}")

        if errors:
            raise ValueError("Invalid configuration: " + "; ".join(errors))
        return self

    # --- Derived helpers -----------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return _split_csv(self.cors_origins)

    @property
    def admin_email_set(self) -> set[str]:
        return {e.lower() for e in _split_csv(self.admin_emails)}

    @property
    def allowed_domain_set(self) -> set[str]:
        return {d.lower() for d in _split_csv(self.allowed_email_domains)}


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
