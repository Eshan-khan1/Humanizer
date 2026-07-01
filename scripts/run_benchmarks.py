#!/usr/bin/env python3
"""Run Humanizer feature benchmarks and write benchmark_results.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTS = ROOT / "benchmark_tests.json"
DEFAULT_OUT = ROOT / "benchmark_results.json"

GRAMMAR_CASES = [
    {
        "id": "g1",
        "name": "Spelling error detected",
        "text": "This is a tset of grammer.",
        "min_matches": 1,
    },
    {
        "id": "g2",
        "name": "Clean text passes",
        "text": "This sentence is correct.",
        "max_matches": 0,
    },
]

REWRITE_FILLER = re.compile(
    r"hope you(?:'re| are) doing well|hope this finds you well|just a quick update",
    re.I,
)


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 120) -> tuple[int, Any, float]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            ms = (time.perf_counter() - start) * 1000
            return resp.status, json.loads(body), ms
    except urllib.error.HTTPError as exc:
        ms = (time.perf_counter() - start) * 1000
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {"detail": str(exc)}
        return exc.code, body, ms
    except Exception as exc:
        ms = (time.perf_counter() - start) * 1000
        return 0, {"detail": str(exc)}, ms


def get_json(url: str, timeout: int = 10) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return 0, {"detail": str(exc)}


def count_sentences(text: str) -> int:
    parts = re.split(r"[.!?]+", text.strip())
    return len([p for p in parts if p.strip()])


def extract_email_body(text: str) -> str:
    lines = text.splitlines()
    body_lines: list[str] = []
    in_body = False
    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            if in_body:
                body_lines.append("")
            continue
        low = stripped.lower()
        if low.startswith("subject:"):
            continue
        if re.match(r"^(dear|hi|hey|hello)\b", low):
            in_body = True
            continue
        if in_body and re.match(
            r"^(best|thanks|thank you|sincerely|regards),?\s*(\[.+\]|[A-Z][a-z].*)?$",
            low,
        ):
            break
        if in_body:
            body_lines.append(stripped)
    return "\n".join(body_lines).strip()


def count_body_paragraphs(text: str) -> int:
    body = extract_email_body(text)
    if not body:
        return 0
    return len([p for p in re.split(r"\n\s*\n", body) if p.strip()])


def body_sentences(text: str) -> list[str]:
    body = extract_email_body(text)
    if not body:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]


def validate_generate(output: str, variant: dict, note: str | None, test_name: str) -> list[str]:
    issues: list[str] = []
    tone = variant.get("tone", "")
    length = variant.get("length", "")
    complexity = variant.get("complexity", "")
    low = output.lower()

    if tone in ("friendly", "casual") and "hope you're doing well" in low:
        issues.append("banned filler: hope you're doing well")
    if tone in ("friendly", "casual") and "hope this finds you well" in low:
        issues.append("banned filler: hope this finds you well")

    if length == "short":
        sents = body_sentences(output)
        if len(sents) > 2:
            issues.append(f"short length: expected <=2 body sentences, got {len(sents)}")
        paras = count_body_paragraphs(output)
        if paras > 1:
            issues.append(f"short length: expected 1 body paragraph, got {paras}")

    if length == "medium":
        paras = count_body_paragraphs(output)
        if paras < 2:
            issues.append(f"medium length: expected multiple paragraphs, got {paras}")

    if length == "long":
        paras = count_body_paragraphs(output)
        sents = len(body_sentences(output))
        if paras < 2:
            issues.append(f"long length: expected 2+ body paragraphs, got {paras}")
        elif paras < 3 and sents < 5:
            issues.append(
                f"long length: expected richer content (3+ paragraphs or 5+ sentences), got {paras} paragraphs / {sents} sentences"
            )

    if complexity == "simple":
        formal = ("pursuant", "commence", "herein", "i am writing to request", "i would like to inquire")
        for phrase in formal:
            if phrase in low:
                issues.append(f"simple complexity: formal phrase '{phrase}'")

    if test_name == "Note Information Only" and note:
        if "family emergency" not in low and "emergency" not in low:
            issues.append("informational note not reflected in output")

    if test_name == "Note Tone Override":
        if "dear " not in low:
            issues.append("note tone override: expected formal Dear greeting")
        if "extension" not in low:
            issues.append("seed topic (extension) missing from body")

    invented = re.findall(r"\b(?:John|Jane|Sarah|Alice|Bob)\b", output)
    if invented:
        issues.append(f"invented names: {', '.join(invented)}")

    return issues


def validate_rewrite(original: str, output: str, instruction: str) -> list[str]:
    issues: list[str] = []
    if REWRITE_FILLER.search(output):
        issues.append("rewrite added banned filler")
    if count_sentences(output) > count_sentences(original) + 1:
        issues.append(
            f"rewrite too long: {count_sentences(output)} sentences vs {count_sentences(original)} original"
        )
    if output.strip().startswith((".", ",", ";")):
        issues.append("rewrite starts with stray punctuation")
    if "!" in output and "!" not in original:
        issues.append("rewrite added exclamation mark")
    low = output.lower()
    if "dear " in low and "dear " not in original.lower():
        issues.append("rewrite added greeting")
    if instruction == "make it formal" and "hey " in low:
        issues.append("formal rewrite still casual (hey)")
    return issues


def run_health(base: str) -> dict:
    status, body = get_json(f"{base}/health")
    ok = status == 200 and body.get("ok") is True
    return {
        "feature": "health",
        "name": "Server health",
        "status": "pass" if ok else "fail",
        "http_status": status,
        "output": body,
        "issues": [] if ok else ["health check failed"],
    }


def run_grammar(base: str) -> list[dict]:
    results = []
    for case in GRAMMAR_CASES:
        status, body, ms = post_json(f"{base}/grammar/quick", {"text": case["text"]})
        matches = body.get("matches", []) if isinstance(body, dict) else []
        issues = []
        if status != 200:
            issues.append(f"http {status}: {body}")
        if "min_matches" in case and len(matches) < case["min_matches"]:
            issues.append(f"expected >={case['min_matches']} matches, got {len(matches)}")
        if "max_matches" in case and len(matches) > case["max_matches"]:
            issues.append(f"expected <={case['max_matches']} matches, got {len(matches)}")
        results.append(
            {
                "feature": "grammar",
                "test_id": case["id"],
                "name": case["name"],
                "status": "pass" if not issues else "fail",
                "duration_ms": round(ms, 1),
                "match_count": len(matches),
                "issues": issues,
            }
        )
    return results


def run_humanize(base: str) -> dict:
    text = "This are a test sentence with bad grammer."
    status, body, ms = post_json(f"{base}/humanize", {"text": text})
    output = body.get("result", body.get("humanized", body.get("text", ""))) if isinstance(body, dict) else ""
    issues = []
    if status != 200:
        issues.append(f"http {status}: {body}")
    elif not output or output.strip() == text.strip():
        issues.append("humanize returned unchanged text")
    return {
        "feature": "humanize",
        "name": "Humanize improves text",
        "status": "pass" if not issues else "fail",
        "duration_ms": round(ms, 1),
        "input": text,
        "output": output,
        "issues": issues,
    }


def run_matrix(base: str, tests: list[dict]) -> list[dict]:
    results = []
    for test in tests:
        for i, variant in enumerate(test.get("variants", []), 1):
            feature = test["feature"]
            note = test.get("note")
            row: dict[str, Any] = {
                "test_id": test["id"],
                "test_name": test["name"],
                "feature": feature,
                "variant": i,
                "input": test["input"],
                "note": note,
            }
            if feature == "generate":
                payload = {
                    "text": test["input"],
                    "format": "email",
                    "settings": {
                        "tonePreset": variant.get("tone", "friendly"),
                        "length": variant.get("length", "medium"),
                        "complexity": variant.get("complexity", "standard"),
                        "includeSubject": True,
                    },
                }
                if note:
                    payload["notes"] = note
                status, body, ms = post_json(f"{base}/generate", payload, timeout=180)
                output = body.get("generated", "") if isinstance(body, dict) else ""
                issues = []
                if status != 200:
                    issues.append(f"http {status}: {body}")
                else:
                    issues = validate_generate(output, variant, note, test["name"])
                row.update(
                    {
                        "variant_settings": variant,
                        "output": output,
                        "status": "pass" if not issues else "fail",
                        "duration_ms": round(ms, 1),
                        "issues": issues,
                    }
                )
            elif feature == "rewrite":
                instruction = variant.get("instruction", "")
                payload = {"text": test["input"], "prompt": instruction}
                status, body, ms = post_json(f"{base}/rewrite", payload, timeout=180)
                output = body.get("rewritten", "") if isinstance(body, dict) else ""
                issues = []
                if status != 200:
                    issues.append(f"http {status}: {body}")
                else:
                    issues = validate_rewrite(test["input"], output, instruction)
                row.update(
                    {
                        "instruction": instruction,
                        "output": output,
                        "status": "pass" if not issues else "fail",
                        "duration_ms": round(ms, 1),
                        "issues": issues,
                    }
                )
            results.append(row)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Humanizer benchmarks")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tests", type=Path, default=DEFAULT_TESTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-grammar", action="store_true")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    all_results: list[dict] = []

    print(f"Benchmarking {base} ...")
    all_results.append(run_health(base))

    if not args.skip_grammar:
        all_results.extend(run_grammar(base))
        all_results.append(run_humanize(base))

    if args.tests.exists():
        tests = json.loads(args.tests.read_text(encoding="utf-8")).get("tests", [])
        all_results.extend(run_matrix(base, tests))
    else:
        print(f"Warning: {args.tests} not found", file=sys.stderr)

    passed = sum(1 for r in all_results if r.get("status") == "pass")
    failed = sum(1 for r in all_results if r.get("status") == "fail")
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "summary": {"total": len(all_results), "passed": passed, "failed": failed},
        "results": all_results,
    }
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Results: {passed} passed, {failed} failed → {args.out}")
    for r in all_results:
        if r.get("status") == "fail":
            name = r.get("test_name") or r.get("name")
            print(f"  FAIL {r.get('feature')} {name}: {', '.join(r.get('issues', []))}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
