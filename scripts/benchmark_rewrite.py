#!/usr/bin/env python3
"""
Benchmark the /rewrite API (Ollama-backed selection rewrite).

Usage:
  ./start_server.sh   # in another terminal
  .venv/bin/python scripts/benchmark_rewrite.py
  .venv/bin/python scripts/benchmark_rewrite.py --limit 15 --json-out test_data/rewrite_benchmark.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
VAL_PATH = ROOT / "val_data.jsonl"
REWRITE_URL = "http://127.0.0.1:8000/rewrite"
HEALTH_URL = "http://127.0.0.1:8000/health"
REQUEST_TIMEOUT = 180

PROMPT_BY_TASK = {
    "rewrite_professional": "Rewrite in a professional tone.",
    "rewrite_casual": "Rewrite in a casual, natural tone.",
    "rewrite_concise": "Rewrite to be more concise.",
}

EMAIL_SPACING_CASES = [
    {
        "id": "email_spacing_chatgpt",
        "input": "Hi Sarah,\n\n\n\nI hope you're doing well.\n\n\n\nI wanted to follow up on our meeting.\n\n\n\nBest,\nAlex",
        "prompt": "Rewrite the text. Fix all grammar errors. Fix all spelling mistakes. Fix all punctuation errors.",
        "checks": ["spacing"],
    },
    {
        "id": "email_greeting_body_signoff",
        "input": "Dear team,\n\nPlease review the attached document by Friday.\n\nThanks,\nJordan",
        "prompt": "make it more professional",
        "checks": ["structure"],
    },
]


@dataclass
class RewriteCase:
    case_id: str
    task: str
    input: str
    reference: str
    prompt: str
    context: dict[str, Any] | None = None
    checks: list[str] = field(default_factory=list)


@dataclass
class RewriteResult:
    case_id: str
    task: str
    ok: bool
    latency_s: float
    similarity: float
    input_len: int
    output_len: int
    prompt: str
    input_text: str
    reference: str
    output: str
    spacing_ok: bool | None = None
    structure_ok: bool | None = None
    error: str = ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def max_blank_run(text: str) -> int:
    runs = re.findall(r"\n+", text or "")
    return max((len(r) for r in runs), default=0)


def structure_line_count(text: str) -> int:
    return len([line for line in (text or "").split("\n") if line.strip()])


def load_val_cases(limit: int | None, tasks: set[str]) -> list[RewriteCase]:
    cases: list[RewriteCase] = []
    if not VAL_PATH.exists():
        return cases

    with VAL_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            task = row.get("task", "")
            if task not in tasks:
                continue
            prompt = PROMPT_BY_TASK.get(task, "Rewrite to sound clear and natural.")
            cases.append(
                RewriteCase(
                    case_id=f"val_{len(cases) + 1}",
                    task=task,
                    input=row["input"],
                    reference=row["output"],
                    prompt=prompt,
                )
            )
            if limit is not None and len(cases) >= limit:
                break
    return cases


def load_email_cases() -> list[RewriteCase]:
    out: list[RewriteCase] = []
    for row in EMAIL_SPACING_CASES:
        out.append(
            RewriteCase(
                case_id=row["id"],
                task="email",
                input=row["input"],
                reference=row["input"],
                prompt=row["prompt"],
                context={
                    "page": {"app": "gmail", "documentType": "email"},
                    "field": {"role": "email_body", "label": "Message body"},
                    "selection": {
                        "excessVerticalSpacing": max_blank_run(row["input"]) > 2,
                        "paragraphLineCount": structure_line_count(row["input"]),
                    },
                },
                checks=row.get("checks", []),
            )
        )
    return out


def call_rewrite(text: str, prompt: str, context: dict[str, Any] | None) -> tuple[str, float]:
    started = time.perf_counter()
    payload: dict[str, Any] = {"text": text, "prompt": prompt}
    if context:
        payload["context"] = context
    response = requests.post(
        REWRITE_URL,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    latency = time.perf_counter() - started
    data = response.json() if response.content else {}
    if not response.ok:
        detail = data.get("detail", response.text)
        raise RuntimeError(f"HTTP {response.status}: {detail}")
    rewritten = (data.get("rewritten") or "").strip()
    if not rewritten:
        raise RuntimeError("empty rewritten text")
    return rewritten, latency


def evaluate_case(case: RewriteCase) -> RewriteResult:
    try:
        output, latency = call_rewrite(case.input, case.prompt, case.context)
        sim = similarity(output, case.reference)
        spacing_ok = None
        structure_ok = None

        if "spacing" in case.checks:
            spacing_ok = max_blank_run(output) <= 2

        if "structure" in case.checks:
            structure_ok = structure_line_count(output) >= 2

        return RewriteResult(
            case_id=case.case_id,
            task=case.task,
            ok=True,
            latency_s=round(latency, 2),
            similarity=round(sim, 3),
            input_len=len(case.input),
            output_len=len(output),
            prompt=case.prompt,
            input_text=case.input,
            reference=case.reference,
            output=output,
            spacing_ok=spacing_ok,
            structure_ok=structure_ok,
        )
    except Exception as exc:  # noqa: BLE001
        return RewriteResult(
            case_id=case.case_id,
            task=case.task,
            ok=False,
            latency_s=0.0,
            similarity=0.0,
            input_len=len(case.input),
            output_len=0,
            prompt=case.prompt,
            input_text=case.input,
            reference=case.reference,
            output="",
            error=str(exc),
        )


def summarize(results: list[RewriteResult]) -> dict[str, Any]:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    by_task: dict[str, list[RewriteResult]] = {}
    for r in ok:
        by_task.setdefault(r.task, []).append(r)

    summary: dict[str, Any] = {
        "total": len(results),
        "success": len(ok),
        "failed": len(failed),
        "success_rate": round(len(ok) / len(results), 3) if results else 0.0,
    }

    if ok:
        summary["latency_s"] = {
            "mean": round(statistics.mean(r.latency_s for r in ok), 2),
            "median": round(statistics.median(r.latency_s for r in ok), 2),
            "p95": round(
                sorted(r.latency_s for r in ok)[max(0, int(len(ok) * 0.95) - 1)],
                2,
            ),
        }
        summary["similarity"] = {
            "mean": round(statistics.mean(r.similarity for r in ok), 3),
            "median": round(statistics.median(r.similarity for r in ok), 3),
        }

    spacing = [r for r in ok if r.spacing_ok is not None]
    if spacing:
        summary["spacing_normalized"] = round(
            sum(1 for r in spacing if r.spacing_ok) / len(spacing), 3
        )

    structure = [r for r in ok if r.structure_ok is not None]
    if structure:
        summary["structure_preserved"] = round(
            sum(1 for r in structure if r.structure_ok) / len(structure), 3
        )

    summary["by_task"] = {}
    for task, rows in sorted(by_task.items()):
        summary["by_task"][task] = {
            "count": len(rows),
            "mean_similarity": round(statistics.mean(r.similarity for r in rows), 3),
            "mean_latency_s": round(statistics.mean(r.latency_s for r in rows), 2),
        }

    if failed:
        summary["errors"] = [{"case_id": r.case_id, "error": r.error} for r in failed]

    return summary


def print_report(results: list[RewriteResult], summary: dict[str, Any]) -> None:
    print("\n=== Humanizer Rewrite Benchmark ===\n")
    print(f"Cases: {summary['total']}  Success: {summary['success']}  Failed: {summary['failed']}")
    print(f"Success rate: {summary['success_rate']:.1%}")

    if "latency_s" in summary:
        lat = summary["latency_s"]
        print(
            f"Latency (s): mean={lat['mean']}  median={lat['median']}  p95={lat['p95']}"
        )

    if "similarity" in summary:
        sim = summary["similarity"]
        print(
            f"Reference similarity: mean={sim['mean']:.3f}  median={sim['median']:.3f}"
        )
        print("  (style rewrites are not expected to match references exactly)")

    if "spacing_normalized" in summary:
        print(f"Email spacing normalized: {summary['spacing_normalized']:.1%}")

    if "structure_preserved" in summary:
        print(f"Email structure preserved: {summary['structure_preserved']:.1%}")

    if summary.get("by_task"):
        print("\nBy task:")
        for task, stats in summary["by_task"].items():
            print(
                f"  {task}: n={stats['count']}  "
                f"similarity={stats['mean_similarity']:.3f}  "
                f"latency={stats['mean_latency_s']:.2f}s"
            )

    print("\nSample outputs:")
    for r in results[:5]:
        if not r.ok:
            print(f"\n[{r.case_id}] FAILED: {r.error}")
            continue
        preview_in = r.input_text.replace("\n", "\\n")[:80]
        preview_out = r.output.replace("\n", "\\n")[:80]
        print(f"\n[{r.case_id}] {r.task}  sim={r.similarity:.3f}  {r.latency_s}s")
        print(f"  in:  {preview_in}{'…' if len(r.input_text) > 80 else ''}")
        print(f"  out: {preview_out}{'…' if len(r.output) > 80 else ''}")

    if summary.get("errors"):
        print("\nFailures:")
        for err in summary["errors"]:
            print(f"  {err['case_id']}: {err['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark /rewrite endpoint")
    parser.add_argument(
        "--limit",
        type=int,
        default=12,
        help="Max val_data rewrite cases per task (default: 12)",
    )
    parser.add_argument(
        "--tasks",
        default="rewrite_professional,rewrite_casual,rewrite_concise",
        help="Comma-separated val_data tasks to include",
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="Skip email spacing/structure cases",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write full results JSON to this path",
    )
    args = parser.parse_args()

    try:
        health = requests.get(HEALTH_URL, timeout=10).json()
    except requests.RequestException as exc:
        print(f"Server not reachable at {HEALTH_URL}: {exc}", file=sys.stderr)
        print("Start it with: OLLAMA_MODEL=humanizer-grammar ./start_server.sh", file=sys.stderr)
        return 1

    if not health.get("ok"):
        print("Health check failed.", file=sys.stderr)
        return 1

    print(f"Server OK  ollama={health.get('ollama_available')}  grammar={health.get('grammar_available')}")

    tasks = {t.strip() for t in args.tasks.split(",") if t.strip()}
    cases = load_val_cases(args.limit, tasks)
    if not args.skip_email:
        cases.extend(load_email_cases())

    if not cases:
        print("No benchmark cases found.", file=sys.stderr)
        return 1

    print(f"Running {len(cases)} rewrite cases…")
    results: list[RewriteResult] = []
    for i, case in enumerate(cases, 1):
        print(f"  [{i}/{len(cases)}] {case.case_id} ({case.task})…", flush=True)
        results.append(evaluate_case(case))

    summary = summarize(results)
    print_report(results, summary)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": summary,
            "results": [asdict(r) for r in results],
        }
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")

    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
