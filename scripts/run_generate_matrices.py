#!/usr/bin/env python3
"""Run Test_data_generating_{N}.json matrices against the live Generate/Rewrite API."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from scripts.run_benchmarks import count_body_paragraphs

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"

TONE_MAP = {
    "formal": "formal",
    "friendly": "warm and friendly",
    "casual": "relaxed and casual",
    "blunt": "blunt and direct",
}
FAB = [
    "trim the hedge",
    "front door",
    "standup is moving",
    "friday standup",
    "cold nights",
    "considerable discomfort",
    "saturday in october",
    "factual:",
    "style:",
    "unforeseen circumstances",
    "personal circumstances",
    "health issues",
    "wedding cake",
    "this concerns a three",
    "this concerns a this",
]
SCAFFOLD = re.compile(
    r"(?i)\b(this concerns|the timing is|this relates to|this involves|the amount is)\b"
)


def parse_profile(raw: str) -> dict:
    profile: dict = {"permanentNote": ""}
    for part in re.split(r",\s*", raw or ""):
        if ":" not in part:
            continue
        key, val = part.split(":", 1)
        key, val = key.strip().lower(), val.strip()
        if key in {"name", "full name"}:
            profile["fullName"] = val
        elif key in {"title", "job title"}:
            profile["jobTitle"] = val
        elif key in {"business", "company"}:
            profile["companyName"] = val
    return profile


def post(path: str, payload: dict) -> tuple[int, dict, float]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return (
                resp.status,
                json.loads(resp.read().decode()),
                round((time.time() - started) * 1000, 1),
            )
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except Exception:
            body = {"detail": str(exc)}
        return exc.code, body, round((time.time() - started) * 1000, 1)
    except Exception as exc:
        return 0, {"detail": str(exc)}, round((time.time() - started) * 1000, 1)


def greeting_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if re.match(r"^(Dear|Hi|Hey|Hello)\b", stripped, re.I):
            return stripped
    return ""


def flatten_cases(raw: dict | list, version: int) -> list[dict]:
    cases = raw["cases"] if isinstance(raw, dict) else raw
    flat: list[dict] = []
    for case in cases:
        # Rewrite cases may use original_text instead of idea.
        if case.get("feature") == "rewrite" and "original_text" in case:
            item = dict(case)
            item["idea"] = case["original_text"]
            item.setdefault("id", str(case.get("id") or case.get("test_id")))
            item.setdefault("scenario", case.get("scenario") or "")
            item.setdefault(
                "settings",
                {
                    "length": "short",
                    "tone": "formal",
                    "complexity": "standard",
                    "profile": "name: Test User",
                    "permanent_note": "",
                },
            )
            flat.append(item)
            continue
        if "idea" in case or ("checks" in case and "input" not in case):
            item = dict(case)
            item.setdefault("feature", "generate")
            item.setdefault("id", str(case.get("id") or case.get("test_id")))
            item.setdefault(
                "scenario", case.get("scenario") or case.get("test_name") or ""
            )
            item["idea"] = case.get("idea") or case.get("original_text") or ""
            flat.append(item)
            continue
        idea = case.get("input") or case.get("idea") or ""
        feature = case.get("feature") or "generate"
        variants = case.get("variants") or [{}]
        tid = case.get("test_id") or case.get("id") or len(flat) + 1
        name = case.get("test_name") or case.get("scenario") or f"test {tid}"
        for index, variant in enumerate(variants, 1):
            tone = variant.get("tone") or "friendly"
            length = variant.get("length") or "medium"
            complexity = variant.get("complexity") or "standard"
            profile = (
                variant.get("profile")
                or case.get("profile")
                or "name: Test User"
            )
            note = (
                variant.get("permanent_note")
                or case.get("permanent_note")
                or ""
            )
            flat.append(
                {
                    "id": f"{version}.{tid}.{index}",
                    "feature": (
                        feature
                        if feature in {"generate", "rewrite"}
                        else "generate"
                    ),
                    "scenario": f"{name} ({tone}/{length}/{complexity})",
                    "idea": idea,
                    "settings": {
                        "length": length,
                        "tone": tone,
                        "complexity": complexity,
                        "profile": profile,
                        "permanent_note": note,
                    },
                    "checks": case.get("checks") or {},
                }
            )
    return flat


def evaluate(case: dict, status: int, payload: dict, output: str) -> list[str]:
    checks = case.get("checks") or {}
    issues: list[str] = []
    if checks.get("reject_http_500") and status == 500:
        issues.append("unexpected HTTP 500")
    if status != 200:
        if not (checks.get("reject_http_500") and status == 500):
            issues.append(f"HTTP {status}: {payload.get('detail')}")
        return issues
    text = output or ""
    if not text.strip():
        issues.append("empty output")
        return issues
    lower = text.lower()
    seed = (case.get("idea") or "").lower()
    greet = greeting_line(text)
    if case.get("feature") == "generate":
        paras = count_body_paragraphs(text)
    else:
        paras = max(
            1,
            len([part for part in re.split(r"\n\s*\n", text) if part.strip()]),
        )
    for entity in checks.get("must_include_entities") or []:
        if entity.lower() not in lower:
            issues.append(f"missing entity: {entity}")
    for group in checks.get("must_include_any") or []:
        if not any(option.lower() in lower for option in group):
            issues.append(f"missing any of: {group}")
    for phrase in checks.get("forbid_phrases") or []:
        if phrase.lower() in lower:
            issues.append(f"forbidden phrase: {phrase}")
    for fact in checks.get("must_preserve_facts") or []:
        if fact.lower() not in lower:
            issues.append(f"missing preserved fact: {fact}")
    for actor in checks.get("must_preserve_actors") or []:
        if actor.lower() not in lower:
            issues.append(f"missing preserved actor: {actor}")
    note = (case.get("settings") or {}).get("permanent_note", "").lower()
    for marker in FAB:
        if marker in lower and marker not in seed and marker not in note:
            message = f"fabricated marker: {marker}"
            if (
                message not in issues
                and f"forbidden phrase: {marker}" not in issues
            ):
                issues.append(message)
    if SCAFFOLD.search(text):
        issues.append(f"scaffold leak: {SCAFFOLD.search(text).group(0)!r}")
    invent_patterns = {
        "Friday": r"\bFriday\b",
        "Saturday": r"\bSaturday\b",
        "October": r"\bOctober\b",
        "2025": r"\b2025\b",
        "2026": r"\b2026\b",
        "next Tuesday": r"\bTuesday\b",
        "appointment Tuesday": r"\bTuesday\b",
    }
    for label in checks.get("must_not_invent") or []:
        pattern = invent_patterns.get(label)
        if not pattern:
            continue
        for match in re.finditer(pattern, text, re.I):
            if match.group(0).lower() in seed:
                continue
            issues.append(f"invented ({label}): {match.group(0)}")
            break
    want = checks.get("must_greeting_name")
    if want and not re.search(
        rf"^(Dear|Hi|Hey|Hello)\s+{re.escape(want)}\s*,?\s*$", greet, re.I
    ):
        issues.append(f"greeting missing name {want!r} (got {greet!r})")
    if checks.get("forbid_greeting_names"):
        if re.match(r"^(Dear|Hi|Hey|Hello)\s+[A-Z][a-z]+", greet) and not re.search(
            r"Sir or Madam|there\b", greet, re.I
        ):
            if not re.match(r"^(Hi|Hey),?\s*$", greet, re.I):
                issues.append(f"unexpected named greeting: {greet!r}")
    if (
        checks.get("must_include_entities")
        or checks.get("must_greeting_name")
        or checks.get("forbid_phrases")
    ):
        if checks.get("min_paragraphs") and paras < checks["min_paragraphs"]:
            issues.append(f"paragraphs {paras} < {checks['min_paragraphs']}")
    return issues


def run_file(version: int, model: str) -> tuple[int, int, list[tuple[str, list[str]]]]:
    source = ROOT / f"Test_data_generating_{version}.json"
    destination = ROOT / f"Test_data_generating_{version}_results.text"
    raw = json.loads(source.read_text(encoding="utf-8"))
    cases = flatten_cases(raw, version)
    passed = failed = 0
    rows: list[dict] = []
    for index, case in enumerate(cases, 1):
        settings_raw = case.get("settings") or {}
        tone = settings_raw.get("tone") or "friendly"
        profile = parse_profile(settings_raw.get("profile") or "")
        if settings_raw.get("permanent_note"):
            profile["permanentNote"] = settings_raw["permanent_note"]
        settings = {
            "tonePreset": tone,
            "tone": TONE_MAP.get(tone, tone),
            "length": settings_raw.get("length") or "medium",
            "complexity": settings_raw.get("complexity") or "standard",
            "includeSubject": True,
            "profile": profile,
        }
        feature = case.get("feature") or "generate"
        idea = case.get("idea") or case.get("original_text") or ""
        if feature == "generate":
            status, body, ms = post(
                "/generate",
                {"text": idea, "format": "email", "settings": settings},
            )
            out = body.get("generated") if status == 200 else ""
        else:
            instruction = case.get("instruction") or TONE_MAP.get(tone, tone)
            status, body, ms = post(
                "/rewrite",
                {"text": idea, "tone": instruction},
            )
            out = body.get("rewritten") if status == 200 else ""
        issues = evaluate(case, status, body, out)
        ok = not issues
        passed += int(ok)
        failed += int(not ok)
        rows.append(
            {
                **case,
                "status": status,
                "ms": ms,
                "ok": ok,
                "issues": issues,
                "output": out or body.get("detail") or "",
            }
        )
        print(
            f"v{version} [{index}/{len(cases)}] "
            f"{'PASS' if ok else 'FAIL'} {case.get('id')} ({ms}ms) {issues[:2]}",
            flush=True,
        )
    lines = [
        f"Humanizer Generate/Rewrite Test Results — {source.name}",
        f"Writing model: {model}",
        f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Summary: {passed}/{passed + failed} passed, {failed}/{passed + failed} failed",
        "",
    ]
    for row in rows:
        lines += [
            f"[{'PASS' if row['ok'] else 'FAIL'}] {row.get('id')} — "
            f"{row.get('scenario')} ({row.get('feature')})",
            f"Settings: {json.dumps(row.get('settings') or {}, ensure_ascii=False)}",
            f"HTTP: {row['status']} | Duration: {row['ms']} ms",
            f"Issues: {'; '.join(row['issues']) if row['issues'] else 'None'}",
            "Output:",
            str(row["output"]),
            "",
            "-" * 80,
            "",
        ]
    destination.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {destination} — {passed}/{passed + failed}", flush=True)
    fails = [(str(row.get("id")), row["issues"]) for row in rows if not row["ok"]]
    return passed, failed, fails


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--versions",
        default="2-9",
        help="Comma list or range like 2-9 / 4,5,8",
    )
    args = parser.parse_args()
    versions: list[int] = []
    for part in args.versions.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            versions.extend(range(int(start), int(end) + 1))
        elif part:
            versions.append(int(part))

    health = json.loads(
        urllib.request.urlopen(BASE + "/health", timeout=10).read().decode()
    )
    model = health.get("writing_model", "unknown")
    print(f"Writing model: {model}", flush=True)

    summary: list[tuple[int, int, int]] = []
    all_fails: list[tuple[int, str, list[str]]] = []
    for version in versions:
        path = ROOT / f"Test_data_generating_{version}.json"
        if not path.exists():
            continue
        print(f"\n===== {path.name} ({model}) =====", flush=True)
        passed, failed, fails = run_file(version, model)
        summary.append((version, passed, failed))
        all_fails.extend((version, case_id, issues) for case_id, issues in fails)

    print("\n======== OVERALL ========", flush=True)
    total_pass = total_fail = 0
    for version, passed, failed in summary:
        print(f"v{version}: {passed}/{passed + failed}", flush=True)
        total_pass += passed
        total_fail += failed
    print(f"TOTAL: {total_pass}/{total_pass + total_fail} on {model}", flush=True)
    if all_fails:
        print("\nFailures:", flush=True)
        for version, case_id, issues in all_fails:
            print(f"  v{version} {case_id}: {issues[:3]}", flush=True)

    summary_path = ROOT / f"Test_data_generating_{model.replace(':', '_').replace('/', '_')}_summary.text"
    summary_path.write_text(
        "\n".join(
            [
                "Qwen3 8B Generate/Rewrite full matrix summary",
                f"Model: {model}",
                f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"Total: {total_pass}/{total_pass + total_fail} passed",
                "",
                *[
                    f"v{version}: {passed}/{passed + failed}"
                    for version, passed, failed in summary
                ],
                "",
                "Failures:" if all_fails else "No failures.",
                *[
                    f"- v{version} {case_id}: {'; '.join(issues[:4])}"
                    for version, case_id, issues in all_fails
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Wrote {summary_path}", flush=True)


if __name__ == "__main__":
    main()
