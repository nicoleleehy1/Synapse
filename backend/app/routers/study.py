"""Flashcards and spaced repetition: generate cards, review them, track mastery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_study
from app.models import (
    Card,
    EntityMastery,
    GenerateCardsRequest,
    GenerateCardsResponse,
    ReviewRequest,
    StudyStats,
)
from app.ratelimit import limit_queries
from app.services.study import StudyService

router = APIRouter(prefix="/study", tags=["study"])


@router.post("/generate", response_model=GenerateCardsResponse, dependencies=[Depends(limit_queries)])
async def generate(request: GenerateCardsRequest, study: StudyService = Depends(get_study)):
    """Have Claude write cards for relationships in the graph that don't have one yet."""
    return GenerateCardsResponse(created=await study.generate(request.document_id, request.count))


@router.get("/due", response_model=list[Card])
async def due(
    document_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    study: StudyService = Depends(get_study),
):
    """Cards to study now: overdue reviews first, then a daily allowance of new cards."""
    return await study.due(document_id, limit)


@router.post("/cards/{card_id}/review", response_model=Card)
async def review(card_id: str, request: ReviewRequest, study: StudyService = Depends(get_study)):
    card = await study.review(card_id, request.rating)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found.")
    return card


@router.get("/mastery", response_model=list[EntityMastery])
async def mastery(study: StudyService = Depends(get_study)):
    """Per-entity recall probability right now, for the graph heatmap."""
    return await study.mastery()


@router.get("/stats", response_model=StudyStats)
async def stats(
    tz_offset_minutes: int = Query(default=0, ge=-840, le=840),
    study: StudyService = Depends(get_study),
):
    return await study.stats(tz_offset_minutes=tz_offset_minutes)
