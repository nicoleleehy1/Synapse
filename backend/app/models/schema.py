import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


def _id() -> str:
    return str(uuid.uuid4())


class TextChunk(BaseModel):
    id: str = Field(default_factory=_id)
    text: str
    page_number: int
    document_id: str
    document_name: str
    char_start: int
    char_end: int
    token_count: int


class Entity(BaseModel):
    id: str = Field(default_factory=_id)
    name: str
    type: str  # PERSON, ORGANIZATION, CONCEPT, LOCATION, EVENT, TECHNOLOGY, OTHER
    description: str | None = None
    source_document: str
    document_id: str | None = None
    source_chunk_ids: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    id: str = Field(default_factory=_id)
    source_entity_id: str
    target_entity_id: str
    type: str  # e.g. WORKS_AT, RELATED_TO, CAUSES, PART_OF, AUTHORED, etc.
    description: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source_chunk_id: str
    source_document: str


class ExtractionResult(BaseModel):
    entities: list[Entity]
    relationships: list[Relationship]


DocumentState = Literal["queued", "processing", "complete", "error"]
PipelineStage = Literal[
    "queued", "parsing", "chunking", "embedding", "extracting", "resolving", "writing", "done"
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class DocumentStatus(BaseModel):
    document_id: str
    filename: str
    status: DocumentState
    stage: PipelineStage = "queued"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    chunks_processed: int = 0
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    page_count: int = 0
    chunk_count: int = 0
    entity_count: int = 0
    relationship_count: int = 0
    error: str | None = None


# --- API models ---


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    message: str


class GraphNode(BaseModel):
    id: str
    name: str
    type: str
    description: str | None = None
    source_document: str
    chunk_count: int = 0


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    description: str | None = None
    confidence: float
    source_document: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    document_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    hop_depth: int = Field(default=2, ge=1, le=3)


class SourceChunk(BaseModel):
    chunk_id: str
    text: str
    page_number: int
    document_name: str
    similarity_score: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    graph_context: GraphResponse
    cypher_used: str | None = None


# --- Graph mutation models ---


class CreateNodeRequest(BaseModel):
    name: str
    type: str = "CONCEPT"
    description: str | None = None
    parent_entity_id: str | None = None
    relationship_type: str | None = None
    relationship_direction: str = "out"  # "out" = parent→new, "in" = new→parent
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class UpdateNodeRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None


class CreateEdgeRequest(BaseModel):
    source_entity_id: str
    target_entity_id: str
    type: str
    description: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class CypherRequest(BaseModel):
    cypher: str = Field(min_length=1, max_length=5000)
    params: dict = Field(default_factory=dict)


class OrphanInfo(BaseModel):
    orphaned_nodes: list[GraphNode] = Field(default_factory=list)


class EdgeOrphanInfo(BaseModel):
    orphaned_target: GraphNode | None = None
