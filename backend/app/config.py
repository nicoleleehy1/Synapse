"""Application settings, loaded from environment variables (and `.env` in development)."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Secrets / connections (no insecure defaults) ──────────────────────────
    anthropic_api_key: str = ""
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str | None = None

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_model: str = "claude-opus-5-5"
    extraction_effort: str = "low"
    answer_effort: str = "medium"
    extraction_concurrency: int = Field(default=8, ge=1, le=64)
    llm_fallbacks: bool = True

    # ── Embeddings ────────────────────────────────────────────────────────────
    # "hash" is a dependency-free offline embedder for local development/tests only.
    embedding_provider: str = "fastembed"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_cache_dir: str | None = None

    # ── Chunking / resolution ─────────────────────────────────────────────────
    chunk_min_tokens: int = 300
    chunk_max_tokens: int = 800
    chunk_overlap_tokens: int = 100
    entity_similarity_threshold: float = 0.88

    # ── Limits / abuse protection ─────────────────────────────────────────────
    max_upload_mb: int = 25
    max_pages: int = 150
    uploads_per_hour: int = 10
    queries_per_hour: int = 120
    cypher_timeout_s: float = 5.0
    cypher_max_rows: int = 500

    # ── HTTP ──────────────────────────────────────────────────────────────────
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    upload_dir: str = "data/uploads"
    # Keep uploaded PDFs so answers and flashcards can open the source page with the
    # passage highlighted. Set false to discard each PDF once it has been processed.
    retain_pdfs: bool = True
    pdf_dir: str = "data/pdfs"

    # ── Study ─────────────────────────────────────────────────────────────────
    desired_retention: float = 0.9
    new_cards_per_session: int = 20
    trust_proxy_headers: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            v = [o.strip() for o in v.split(",") if o.strip()]
        if isinstance(v, list):
            # Hosting platforms often inject bare hostnames; assume HTTPS.
            return [o if o.startswith(("http://", "https://")) else f"https://{o}" for o in v]
        return v

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
