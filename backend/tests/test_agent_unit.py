from app.services.agent import AgentRun, tool_definitions


def test_tool_schemas_are_strict_compatible():
    tools = tool_definitions()
    assert {t["name"] for t in tools} == {
        "search_passages",
        "search_entities",
        "explore_entities",
        "search_topics",
        "run_cypher",
    }
    for t in tools:
        schema = t["input_schema"]
        assert t["strict"] is True
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        for prop in schema["properties"].values():
            assert not {"default", "minimum", "maximum", "title"} & set(prop)


def test_citations_are_numbered_once_per_chunk():
    run = AgentRun()
    hit = {"chunk_id": "c1", "text": "t", "page_number": 1, "document_name": "d.pdf", "score": 0.9}
    assert run.cite(hit) == 1
    assert run.cite({**hit, "chunk_id": "c2"}) == 2
    assert run.cite(hit) == 1
    assert len(run.sources) == 2
