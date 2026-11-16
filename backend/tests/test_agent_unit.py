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


async def test_unexpected_client_failure_ends_with_an_error_event():
    from types import SimpleNamespace

    from app.services.agent import GraphRAGAgent

    class Broken:
        def stream(self, **kwargs):
            raise TypeError("Could not resolve authentication method")

    client = SimpleNamespace(messages=Broken(), beta=SimpleNamespace(messages=Broken()))
    agent = GraphRAGAgent(graph_store=None, client=client)  # type: ignore[arg-type]
    events = [e async for e in agent.run("hi")]
    assert events[-1]["type"] == "error"
    assert "ANTHROPIC_API_KEY" in events[-1]["message"]
