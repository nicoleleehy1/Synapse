"""Sanity checks for the eval harness: the labelled set must be answerable from the corpus."""

import json
import os

import anthropic
import pymupdf
import pytest

from eval.run_eval import load_corpus, load_questions, summarise, to_markdown, write_pdf


def test_questions_are_well_formed_and_grounded():
    questions = load_questions()
    corpus = " ".join(load_corpus().values()).lower()
    assert len({q.id for q in questions}) == len(questions)
    assert {q.kind for q in questions} >= {"local", "multi-hop", "global", "unanswerable"}
    for q in questions:
        for fact in q.facts:
            assert fact.lower() in corpus, f"{q.id}: key fact {fact!r} is not in the corpus"
        assert q.facts or q.kind == "unanswerable"


def test_corpus_round_trips_through_pdf(tmp_path):
    for name, text in load_corpus().items():
        path = tmp_path / f"{name}.pdf"
        write_pdf(path, text)
        with pymupdf.open(path) as doc:
            extracted = " ".join(page.get_text() for page in doc)
        last_words = text.split()[-3:]
        assert all(w in extracted for w in last_words), f"{name} was truncated in the PDF"


def test_summary_and_report():
    def row(qid, kind, system, correctness, covered, n, halluc=False):
        return {
            "id": qid,
            "kind": kind,
            "question": "q?",
            "system": system,
            "answer": "a",
            "correctness": correctness,
            "facts_covered": covered,
            "n_facts": n,
            "hallucination": halluc,
            "rationale": "r",
            "latency_ms": 1000,
            "steps": 0,
        }

    rows = [
        row("m1", "multi-hop", "baseline", 2, [0], 2),
        row("m1", "multi-hop", "agent", 5, [0, 1], 2),
        row("n1", "unanswerable", "baseline", 0, [], 0, halluc=True),
        row("n1", "unanswerable", "agent", 5, [], 0),
    ]
    s = summarise(rows)
    assert s["multi-hop"]["agent"]["fact_recall"] == 1.0
    assert s["multi-hop"]["baseline"]["fact_recall"] == 0.5
    assert s["all"]["agent"]["correctness"] == 5
    assert s["all"]["baseline"]["hallucination_rate"] == 0.5
    assert s["unanswerable"]["agent"]["fact_recall"] != s["unanswerable"]["agent"]["fact_recall"]  # NaN
    md = to_markdown(s, rows, {"timestamp": "t", "model": "m", "questions": 2, "documents": 3})
    assert "| multi-hop | agent | 5.00 | 100% | 0% | 1.0s |" in md
    assert "| unanswerable | agent | 5.00 | n/a |" in md


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("NEO4J_TEST_URI"), reason="NEO4J_TEST_URI not set")
async def test_run_eval_end_to_end_with_fake_claude(monkeypatch, tmp_path):
    """Drive the whole harness (ingest, both systems, judge, report, cleanup) with a fake client."""
    from app.config import settings
    from app.services.communities import _Report
    from app.services.extractor import _ExtractionPayload
    from app.services.graph_store import GraphStore
    from eval import run_eval
    from tests.fakes import ScriptedAnthropic

    names = ["Meridian Tidal Power", "Brightwater Composites", "Westcoast Grid", "Priya Raman"]

    def parse(kwargs):
        fmt = kwargs["output_format"]
        if fmt is _ExtractionPayload:
            text = kwargs["messages"][0]["content"]
            ents = [{"name": n, "type": "ORGANIZATION", "description": n} for n in names if n in text]
            rels = [
                {
                    "source": a["name"],
                    "target": b["name"],
                    "type": "RELATED_TO",
                    "description": "",
                    "confidence": 0.9,
                }
                for a, b in zip(ents, ents[1:], strict=False)
            ]
            return _ExtractionPayload.model_validate({"entities": ents, "relationships": rels})
        if fmt is _Report:
            return _Report(title="Tidal energy", summary="About tidal power.", findings=["One."])
        if fmt is run_eval.Verdict:
            return run_eval.Verdict(correctness=7, facts_covered=[0, 99], hallucination=False, rationale="ok")
        raise AssertionError(fmt)

    fake = ScriptedAnthropic([], parse_fn=parse, text="Answer [1].")
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: fake)
    monkeypatch.setattr(settings, "anthropic_api_key", "test")
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)

    gs = GraphStore()
    await gs.connect()
    try:
        await gs._run(
            "MATCH (n) WHERE n:Entity OR n:Chunk OR n:Document OR n:Community OR n:Card OR n:Review DETACH DELETE n"
        )
        assert await run_eval.main(["--only", "local-1", "neg-1"]) == 0
        assert await gs.list_documents() == []  # corpus cleaned up
    finally:
        await gs.close()

    data = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert {(r["id"], r["system"]) for r in data["rows"]} == {
        ("local-1", "baseline"),
        ("local-1", "agent"),
        ("neg-1", "baseline"),
        ("neg-1", "agent"),
    }
    row = next(r for r in data["rows"] if r["id"] == "local-1")
    assert row["correctness"] == 5 and row["facts_covered"] == [0]  # judge output is clamped
    assert (tmp_path / next(tmp_path.glob("*.md")).name).read_text().startswith("# Synapse eval")
