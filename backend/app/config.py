from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    anthropic_api_key: str
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    embedding_model: str = "all-MiniLM-L6-v2"
    faiss_index_path: str = "data/faiss.index"
    faiss_metadata_path: str = "data/faiss_metadata.json"
    chunk_min_tokens: int = 300
    chunk_max_tokens: int = 800
    chunk_overlap_tokens: int = 100
    entity_similarity_threshold: float = 0.88
    llm_model: str = "claude-sonnet-4-6"
    upload_dir: str = "data/uploads"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = {"env_file": ".env"}


settings = Settings()

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path("data").mkdir(exist_ok=True)
