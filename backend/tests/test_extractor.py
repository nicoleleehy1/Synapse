from types import SimpleNamespace

import pytest

from app.models import TextChunk
from app.services.extractor import Extractor, _ExtractionPayload
from tests.fakes import FakeAnthropic

CHUNK = TextChunk(
    id="c1",
    text="Ada Lovelace worked with Charles Babbage on the Analytical Engine.",
    page_number=3,
    document_id="d1",
    document_name="history.pdf",
    char_start=0,
    char_end=60,
    token_count=12,
)

PAYLOAD = _ExtractionPayload.model_validate(
    {
        "entities": [
            {"name": "Ada Lovelace", "type": "PERSON", "description": "Mathematician."},
            {"name": "Charles Babbage", "type": "PERSON", "description": "Inventor."},
            {"name": "Analytical Engine", "type": "TECHNOLOGY", "description": "Early computer design."},
            {"name": "ada lovelace", "type": "PERSON", "description": "duplicate casing"},
        ],
        "relationships": [
            {
                "source": "Ada Lovelace",
                "target": "Charles Babbage",
                "type": "collaborated with",
                "description": "Worked together.",
                "confidence": 1.7,
            },
            {
                "source": "Charles Babbage",
                "target": "Analytical Engine",
                "type": "DESIGNED",
                "description": "Designed it.",
                "confidence": 0.9,
            },
            {
                "source": "Ada Lovelace",
                "target": "Nobody",
                "type": "KNOWS",
                "description": "dangling",
                "confidence": 0.5,
            },
        ],
    }
)


def test_to_graph_maps_and_cleans():
    res = Extractor.to_graph(PAYLOAD, CHUNK)
    assert [e.name for e in res.entities] == ["Ada Lovelace", "Charles Babbage", "Analytical Engine"]
    assert all(e.source_chunk_ids == ["c1"] and e.document_id == "d1" for e in res.entities)
    assert len(res.relationships) == 2  # dangling one dropped
    collab = res.relationships[0]
    assert collab.type == "COLLABORATED_WITH"
    assert collab.confidence == 1.0  # clamped
    assert collab.source_chunk_id == "c1"


async def test_extract_uses_structured_output_and_fallbacks():
    fake = FakeAnthropic(parse_fn=lambda kw: PAYLOAD)
    res = await Extractor(client=fake).extract_from_chunk(CHUNK)
    assert len(res.entities) == 3
    call = fake.messages.calls[0]
    assert call["output_format"] is _ExtractionPayload
    assert call["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in call["betas"]
    assert call["output_config"]["effort"] == "low"
    assert CHUNK.text in call["messages"][0]["content"]


@pytest.mark.parametrize("reason", ["refusal", "max_tokens"])
async def test_extract_degrades_on_unusable_stop_reason(reason):
    fake = FakeAnthropic(parse_fn=lambda kw: SimpleNamespace(stop_reason=reason, parsed_output=None))
    res = await Extractor(client=fake).extract_from_chunk(CHUNK)
    assert res.entities == [] and res.relationships == []
