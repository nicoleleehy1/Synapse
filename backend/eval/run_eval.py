"""Compare the fixed retrieval pipeline with the GraphRAG agent on a small labelled corpus.

    cd backend
    ANTHROPIC_API_KEY=... NEO4J_URI=... NEO4J_PASSWORD=... python -m eval.run_eval

What it does:

1. Turns the fictional corpus in eval/corpus/ into PDFs and ingests them through the
   real pipeline (extraction, entity resolution, cross-document merge), then builds
   the community hierarchy.
2. Asks every question in eval/questions.json to two systems:
   - baseline: the original fixed pipeline (vector search -> graph expansion -> answer)
   - agent: the tool-using GraphRAG agent
3. A Claude judge grades each answer against a reference answer and a list of key
   facts, blind to which system wrote it.
4. Writes eval/results/<timestamp>.{json,md} and prints the summary table.

The questions are split by kind (local lookups, multi-hop across documents,
aggregation, global "big picture", and one unanswerable question) so the report
shows where the agent's tools help and where they don't.

The corpus documents are deleted afterwards unless --keep is passed. Run it against an
empty database: the global questions assume the graph contains only this corpus.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
import pymupdf
from pydantic import BaseModel, Field

from app.config import settings
from app.models import DocumentStatus, QueryRequest
from app.services.agent import GraphRAGAgent
from app.services.communities import CommunityBuilder
from app.services.graph_store import GraphStore
from app.services.pipeline import Pipeline
from app.services.retriever import Retriever

HERE = Path(__file__).parent
CORPUS_DIR = HERE / "corpus"
QUESTIONS_FILE = HERE / "questions.json"
RESULTS_DIR = HERE / "results"
SYSTEMS = ("baseline", "agent")


# ── Data ──────────────────────────────────────────────────────────────────────


class Question(BaseModel):
    id: str
    kind: str
    question: str
    reference: str
    facts: list[str]


def load_questions(path: Path = QUESTIONS_FILE) -> list[Question]:
    return [Question.model_validate(q) for q in json.loads(path.read_text())]


def load_corpus(directory: Path = CORPUS_DIR) -> dict[str, str]:
    return {p.stem: p.read_text() for p in sorted(directory.glob("*.md"))}


def write_pdf(path: Path, text: str) -> None:
    """One paragraph block per page if the whole text doesn't fit on one."""
    doc = pymupdf.open()
    rect = pymupdf.Rect(50, 50, 550, 800)
    page = doc.new_page()
    if page.insert_textbox(rect, text, fontsize=10) < 0:
        doc.delete_page(0)
        for para in (p for p in text.split("\n\n") if p.strip()):
            doc.new_page().insert_textbox(rect, para, fontsize=10)
    doc.save(str(path))
    doc.close()


# ── Judge ─────────────────────────────────────────────────────────────────────


class Verdict(BaseModel):
    correctness: int = Field(description="0-5. 5 = fully correct and complete, 0 = wrong or no answer.")
    facts_covered: list[int] = Field(description="Indices (from 0) of the key facts the answer states.")
    hallucination: bool = Field(
        description="True if the answer asserts anything not supported by the reference."
    )
    rationale: str = Field(description="One or two sentences explaining the grade.")


JUDGE_SYSTEM = """You grade answers to questions about a small document collection.

You get the question, a reference answer written by someone who read the documents, a
numbered list of key facts, and a candidate answer. Grade only the candidate's content
against the reference: ignore style, length and citation markers like [1].

correctness: 5 fully correct and complete; 4 correct with a minor omission; 3 partly
correct; 2 mostly incomplete; 1 largely wrong; 0 wrong, empty or refuses without reason.
For a question the documents cannot answer, a candidate that says so plainly gets 5 and
one that invents an answer gets 0.

facts_covered: the indices of key facts the candidate states, allowing paraphrase
("five" = "5", "EUR 22m" = "22 million euros").

hallucination: true only if the candidate asserts a specific claim that contradicts or
goes beyond the reference and key facts."""


async def judge(client: anthropic.AsyncAnthropic, q: Question, answer: str) -> Verdict:
    facts = "\n".join(f"{i}. {f}" for i, f in enumerate(q.facts)) or "(none: the question is unanswerable)"
    prompt = (
        f"<question>{q.question}</question>\n<reference>{q.reference}</reference>\n"
        f"<key_facts>\n{facts}\n</key_facts>\n<candidate>{answer}</candidate>"
    )
    resp = await client.messages.parse(
        model=settings.llm_model,
        max_tokens=2000,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=Verdict,
        output_config={"effort": "low"},
    )
    if resp.parsed_output is None:
        raise RuntimeError(f"Judge returned no verdict (stop_reason={resp.stop_reason})")
    v: Verdict = resp.parsed_output
    v.facts_covered = sorted({i for i in v.facts_covered if 0 <= i < len(q.facts)})
    v.correctness = max(0, min(5, v.correctness))
    return v


# ── Systems under test ────────────────────────────────────────────────────────


async def ask_baseline(retriever: Retriever, q: Question) -> dict[str, Any]:
    t0 = time.perf_counter()
    resp = await retriever.query(QueryRequest(query=q.question))
    return {"answer": resp.answer, "latency_ms": int((time.perf_counter() - t0) * 1000), "steps": 0}


async def ask_agent(agent: GraphRAGAgent, q: Question) -> dict[str, Any]:
    t0 = time.perf_counter()
    result = await agent.answer(q.question)
    if result["type"] == "error":
        return {
            "answer": "",
            "error": result["message"],
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "steps": 0,
        }
    return {
        "answer": result["answer"],
        "latency_ms": result["latency_ms"],
        "steps": result["steps"],
        "usage": result.get("usage"),
    }


# ── Reporting ─────────────────────────────────────────────────────────────────


def summarise(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    """{kind or "all": {system: {correctness, fact_recall, hallucination_rate, latency_ms, n}}}."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    kinds = sorted({r["kind"] for r in rows}) + ["all"]
    for kind in kinds:
        out[kind] = {}
        for system in SYSTEMS:
            sel = [r for r in rows if r["system"] == system and (kind == "all" or r["kind"] == kind)]
            if not sel:
                continue
            with_facts = [r for r in sel if r["n_facts"]]
            out[kind][system] = {
                "n": len(sel),
                "correctness": statistics.mean(r["correctness"] for r in sel),
                "fact_recall": (
                    statistics.mean(len(r["facts_covered"]) / r["n_facts"] for r in with_facts)
                    if with_facts
                    else float("nan")
                ),
                "hallucination_rate": statistics.mean(1.0 if r["hallucination"] else 0.0 for r in sel),
                "latency_ms": statistics.median(r["latency_ms"] for r in sel),
            }
    return out


def to_markdown(
    summary: dict[str, dict[str, dict[str, float]]], rows: list[dict[str, Any]], meta: dict
) -> str:
    def fmt(x: float, pct: bool = False) -> str:
        if x != x:  # NaN
            return "n/a"
        return f"{x * 100:.0f}%" if pct else f"{x:.2f}"

    lines = [
        f"# Synapse eval, {meta['timestamp']}",
        "",
        f"Model `{meta['model']}`, {meta['questions']} questions, {meta['documents']} documents. "
        "Correctness is the judge's 0-5 grade; fact recall is the share of key facts stated.",
        "",
        "| Kind | System | Correctness | Fact recall | Hallucination | Median latency |",
        "|---|---|---|---|---|---|",
    ]
    for kind, by_system in summary.items():
        for system, m in by_system.items():
            lines.append(
                f"| {kind} | {system} | {fmt(m['correctness'])} | {fmt(m['fact_recall'], True)} | "
                f"{fmt(m['hallucination_rate'], True)} | {m['latency_ms'] / 1000:.1f}s |"
            )
    lines += ["", "## Answers", ""]
    for qid in dict.fromkeys(r["id"] for r in rows):
        group = [r for r in rows if r["id"] == qid]
        lines += [f"### {qid}: {group[0]['question']}", ""]
        for r in group:
            lines += [
                f"**{r['system']}** ({r['correctness']}/5, {len(r['facts_covered'])}/{r['n_facts']} facts"
                + (", hallucination" if r["hallucination"] else "")
                + f"): {r['rationale']}",
                "",
                "> " + (r["answer"] or r.get("error") or "(no answer)").replace("\n", "\n> "),
                "",
            ]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────


async def ingest(gs: GraphStore, corpus: dict[str, str], workdir: Path) -> list[str]:
    pipeline = Pipeline(graph_store=gs)
    ids = []
    for name, text in corpus.items():
        path = workdir / f"{name}.pdf"
        write_pdf(path, text)
        status = DocumentStatus(document_id=str(uuid.uuid4()), filename=path.name, status="queued")
        await gs.save_document(status)
        ids.append(status.document_id)
        print(f"  ingesting {path.name} ...", flush=True)
        result = await pipeline.process(path, status)
        if result.status != "complete":
            raise RuntimeError(f"Ingesting {path.name} failed: {result.error}")
        print(f"    {result.entity_count} entities, {result.relationship_count} relationships", flush=True)
    print("  building topic hierarchy ...", flush=True)
    await CommunityBuilder(graph_store=gs).rebuild()
    return ids


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true", help="keep the corpus in the database afterwards")
    ap.add_argument("--skip-ingest", action="store_true", help="reuse a corpus ingested with --keep")
    ap.add_argument("--allow-existing", action="store_true", help="run even if other documents exist")
    ap.add_argument("--only", nargs="*", help="question ids to run")
    ap.add_argument("--concurrency", type=int, default=3)
    args = ap.parse_args(argv)

    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is required: the eval calls Claude for extraction, answers and judging.")
        return 2

    questions = load_questions()
    if args.only:
        questions = [q for q in questions if q.id in set(args.only)]
    corpus = load_corpus()

    gs = GraphStore()
    await gs.connect()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    doc_ids: list[str] = []
    try:
        existing = await gs.list_documents()
        if existing and not args.skip_ingest and not args.allow_existing:
            print(
                f"The database already has {len(existing)} document(s). Use an empty database, "
                "or pass --allow-existing (global questions will then be skewed)."
            )
            return 2

        if not args.skip_ingest:
            print("Ingesting corpus")
            with tempfile.TemporaryDirectory() as tmp:
                doc_ids = await ingest(gs, corpus, Path(tmp))

        retriever, agent = Retriever(graph_store=gs), GraphRAGAgent(graph_store=gs)
        sem = asyncio.Semaphore(args.concurrency)

        async def one(q: Question, system: str) -> dict[str, Any]:
            async with sem:
                res = await (ask_baseline(retriever, q) if system == "baseline" else ask_agent(agent, q))
                v = await judge(client, q, res["answer"])
            print(f"  {q.id:<10} {system:<9} {v.correctness}/5", flush=True)
            return {
                "id": q.id,
                "kind": q.kind,
                "question": q.question,
                "system": system,
                "n_facts": len(q.facts),
                **res,
                **v.model_dump(),
            }

        print("Asking questions")
        jobs = [(q, s) for q in questions for s in SYSTEMS]
        random.Random(0).shuffle(jobs)  # interleave so neither system benefits from warm caches
        rows = await asyncio.gather(*(one(q, s) for q, s in jobs))
        rows.sort(key=lambda r: ([q.id for q in questions].index(r["id"]), SYSTEMS.index(r["system"])))

        summary = summarise(rows)
        meta = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "model": settings.llm_model,
            "questions": len(questions),
            "documents": len(corpus),
        }
        RESULTS_DIR.mkdir(exist_ok=True)
        stem = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        (RESULTS_DIR / f"{stem}.json").write_text(
            json.dumps({"meta": meta, "summary": summary, "rows": rows}, indent=2)
        )
        report = to_markdown(summary, rows, meta)
        (RESULTS_DIR / f"{stem}.md").write_text(report)
        print("\n" + report.split("\n## Answers")[0])
        print(f"Full report: {RESULTS_DIR / (stem + '.md')}")
        return 0
    finally:
        if doc_ids and not args.keep:
            for d in doc_ids:
                await gs.delete_document(d)
            await CommunityBuilder(graph_store=gs).rebuild()
        await gs.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
