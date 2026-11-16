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
    # Rectangles on the PDF page, as fractions of page size: {page, x0, y0, x1, y1}.
    highlights: list[dict[str, float]] = Field(default_factory=list)


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
    document_id: str | None = None


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


class AgentQueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    graph_context: GraphResponse
    highlight_ids: list[str] = Field(default_factory=list)
    steps: int = 0
    latency_ms: int = 0


class CommunityOut(BaseModel):
    id: str
    level: int
    title: str
    summary: str
    findings: list[str] = Field(default_factory=list)
    size: int
    parent_id: str | None = None
    member_ids: list[str] = Field(default_factory=list)


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


# --- Source viewer and study ---


class Highlight(BaseModel):
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class ChunkDetail(BaseModel):
    chunk_id: str
    text: str
    page_number: int
    document_id: str
    document_name: str
    highlights: list[Highlight]
    has_pdf: bool


class Card(BaseModel):
    id: str
    front: str
    back: str
    chunk_id: str | None
    document_id: str | None
    entity_ids: list[str]
    entity_names: list[str]
    state: Literal["new", "review", "relearning"]
    reps: int
    lapses: int
    due_ms: int
    # What each rating (1 Again, 2 Hard, 3 Good, 4 Easy) would schedule, in seconds from now.
    intervals: dict[int, int]


class GenerateCardsRequest(BaseModel):
    document_id: str | None = None
    count: int = Field(default=12, ge=1, le=40)


class GenerateCardsResponse(BaseModel):
    created: int


class ReviewRequest(BaseModel):
    rating: Literal[1, 2, 3, 4]


class EntityMastery(BaseModel):
    entity_id: str
    mastery: float  # mean recall probability of the entity's cards, 0-1
    cards: int
    due: int


class StudyStats(BaseModel):
    total: int
    new: int
    due: int
    reviewed_today: int
    retention_30d: float | None
    streak_days: int
    activity: list[int]  # reviews per day for the last 14 days, oldest first
