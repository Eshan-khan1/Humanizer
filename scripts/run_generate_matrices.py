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
from claim_check import (
    claim_check_draft,
    claim_check_summary,
    format_claim_checklist,
)

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
    "looking forward to",
    "don't hesitate",
    "do not hesitate",
    "reaching out",
    "hope this finds you",
    "please use august",
    "this happened yesterday",
    "make more friendly",
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
        elif key and val:
            # Preserve member ID / account / unit / etc. for claim checking.
            safe_key = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
            if safe_key and safe_key not in {"permanent_note", "permanentnote"}:
                profile[safe_key] = val
    return profile


def post(path: str, payload: dict) -> tuple[int, dict, float]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    last_body: dict = {}
    last_code = 0
    for attempt in range(8):
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
            last_body, last_code = body, exc.code
            detail = str(body.get("detail") or "").lower()
            rate_limited = exc.code in {429, 413, 500, 502, 503} and (
                "rate limit" in detail
                or "try again" in detail
                or "tokens per" in detail
                or "request too large" in detail
                or exc.code == 429
            )
            if rate_limited and attempt < 7:
                time.sleep(min(120.0, 15.0 * (2**attempt)))
                continue
            return exc.code, body, round((time.time() - started) * 1000, 1)
        except Exception as exc:
            last_body, last_code = {"detail": str(exc)}, 0
            if attempt < 7:
                time.sleep(2.0 * (attempt + 1))
                continue
            return 0, last_body, round((time.time() - started) * 1000, 1)
    return last_code, last_body, round((time.time() - started) * 1000, 1)


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


def _entity_present(entity: str, text_lower: str) -> bool:
    """Loose match for entities that commonly change formatting (times, am/pm)."""
    needle = (entity or "").lower().strip()
    if not needle:
        return True
    if needle in text_lower:
        return True
    # 8am ↔ 8 am ↔ 8:00 am ↔ 8 AM
    time_match = re.fullmatch(r"(\d{1,2})\s*([ap]m)", needle)
    if time_match:
        hour, meridiem = time_match.group(1), time_match.group(2)
        if re.search(rf"\b{hour}(?::00)?\s*{meridiem}\b", text_lower):
            return True
    # 2 days ↔ two days
    num_words = {
        "1": "one",
        "2": "two",
        "3": "three",
        "4": "four",
        "5": "five",
        "6": "six",
        "7": "seven",
        "8": "eight",
        "9": "nine",
        "10": "ten",
    }
    num_match = re.fullmatch(r"(\d+)\s+(days?|weeks?|months?)", needle)
    if num_match and num_match.group(1) in num_words:
        alt = f"{num_words[num_match.group(1)]} {num_match.group(2)}"
        if alt in text_lower:
            return True
    # Collapse punctuation/spacing: "214 Willow" vs "214, Willow"
    compact_needle = re.sub(r"[\s,]+", " ", needle)
    compact_text = re.sub(r"[\s,]+", " ", text_lower)
    if compact_needle in compact_text:
        return True
    # Order IDs: #PN-4410 ↔ PN-4410 ↔ pn 4410
    id_match = re.fullmatch(r"#?([a-z]{1,4})-?(\d{2,})", needle)
    if id_match:
        prefix, digits = id_match.group(1), id_match.group(2)
        if re.search(rf"#?\s*{prefix}\s*-?\s*{digits}\b", text_lower):
            return True
    # noon ↔ 12 pm
    if needle == "noon" and re.search(r"\b12\s*(?::00)?\s*(?:pm|noon)\b", text_lower):
        return True
    return False


def evaluate(
    case: dict, status: int, payload: dict, output: str
) -> tuple[list[str], list[str], list[str]]:
    checks = case.get("checks") or {}
    issues: list[str] = []
    warnings: list[str] = []
    claim_lines: list[str] = []
    if checks.get("reject_http_500") and status == 500:
        issues.append("unexpected HTTP 500")
    if status != 200:
        if not (checks.get("reject_http_500") and status == 500):
            issues.append(f"HTTP {status}: {payload.get('detail')}")
        return issues, warnings, claim_lines
    text = output or ""
    if not text.strip():
        issues.append("empty output")
        return issues, warnings, claim_lines
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
        if not _entity_present(entity, lower):
            issues.append(f"missing entity: {entity}")
    for group in checks.get("must_include_any") or []:
        if not any(_entity_present(option, lower) for option in group):
            issues.append(f"missing any of: {group}")
    for phrase in checks.get("forbid_phrases") or []:
        if phrase.lower() in lower:
            issues.append(f"forbidden phrase: {phrase}")
    for fact in checks.get("must_preserve_facts") or []:
        if not _entity_present(fact, lower):
            issues.append(f"missing preserved fact: {fact}")
    for actor in checks.get("must_preserve_actors") or []:
        if not _entity_present(actor, lower):
            issues.append(f"missing preserved actor: {actor}")
    if SCAFFOLD.search(text):
        issues.append(f"scaffold leak: {SCAFFOLD.search(text).group(0)!r}")
    want = checks.get("must_greeting_name")
    if want and not re.search(
        rf"^(Dear|Hi|Hey|Hello)\s+(?:(?:Professor|Prof\.|Dr\.|Mr\.|Ms\.|Mrs\.)\s+)?"
        rf"{re.escape(want)}\b",
        greet,
        re.I,
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

    settings = case.get("settings") or {}
    profile = parse_profile(settings.get("profile") or "")
    findings = claim_check_draft(
        text,
        seed=case.get("idea") or case.get("original_text") or "",
        permanent_note=settings.get("permanent_note") or "",
        profile=profile,
    )
    claim_lines = format_claim_checklist(findings)
    problem_count = sum(
        1 for f in findings if f.classification in {"fabricated", "missing"}
    )
    if problem_count:
        warnings.append(claim_check_summary(findings))

    # Known catastrophic bleed phrases still surface as warnings if somehow missed.
    note = (settings.get("permanent_note") or "").lower()
    stock_filler = {
        "looking forward to",
        "don't hesitate",
        "do not hesitate",
        "reaching out",
        "hope this finds you",
        "please use august",
        "this happened yesterday",
        "make more friendly",
        "factual:",
        "style:",
    }
    for marker in FAB:
        if marker in lower and marker not in seed and marker not in note:
            msg = f"known bleed phrase: {marker}"
            if marker in stock_filler:
                if f"forbidden phrase: {marker}" not in issues and msg not in issues:
                    issues.append(msg)
            elif msg not in warnings and f"forbidden phrase: {marker}" not in issues:
                warnings.append(msg)
    return issues, warnings, claim_lines


def _flagged_claim_lines(claim_lines: list[str]) -> list[str]:
    return [
        line
        for line in claim_lines
        if "[fabricated]" in line or "[missing]" in line
    ]


def _run_case_once(case: dict) -> dict:
    """Single request + evaluate + claim-check (unchanged per-run logic)."""
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
    notes = str(case.get("notes") or "").strip()
    if feature == "generate":
        status, body, ms = post(
            "/generate",
            {
                "text": idea,
                "format": "email",
                "notes": notes,
                "settings": settings,
            },
        )
        out = body.get("generated") if status == 200 else ""
    else:
        instruction = case.get("instruction") or TONE_MAP.get(tone, tone)
        status, body, ms = post(
            "/rewrite",
            {"text": idea, "tone": instruction},
        )
        out = body.get("rewritten") if status == 200 else ""
    issues, warnings, claim_lines = evaluate(case, status, body, out)
    return {
        "status": status,
        "ms": ms,
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "claim_lines": claim_lines,
        "output": out or body.get("detail") or "",
    }


def _aggregate_case_runs(case: dict, runs: list[dict], repeats: int) -> dict:
    """Collapse N identical-input runs into one summary row."""
    pass_count = sum(1 for run in runs if run["ok"])
    finding_counts: dict[str, int] = {}
    for run in runs:
        for line in run.get("claim_lines") or []:
            finding_counts[line] = finding_counts.get(line, 0) + 1

    # Prefer an example from a run that had fabricated/missing findings.
    example = next(
        (run for run in runs if _flagged_claim_lines(run.get("claim_lines") or [])),
        runs[0] if runs else {},
    )

    runs_with_claim_issues = sum(
        1 for run in runs if _flagged_claim_lines(run.get("claim_lines") or [])
    )
    if runs_with_claim_issues == 0:
        claim_stability = "clean"
    elif runs_with_claim_issues == repeats:
        claim_stability = "always"
    else:
        claim_stability = "flaky"

    return {
        **case,
        "repeats": repeats,
        "pass_count": pass_count,
        "ok": pass_count == repeats,
        "runs_with_claim_issues": runs_with_claim_issues,
        "claim_stability": claim_stability,
        "finding_counts": finding_counts,
        "avg_ms": round(sum(run["ms"] for run in runs) / max(len(runs), 1), 1),
        "example_output": example.get("output", ""),
        "example_from_flagged": bool(
            _flagged_claim_lines(example.get("claim_lines") or [])
        ),
        "issues_union": sorted(
            {issue for run in runs for issue in (run.get("issues") or [])}
        ),
    }


def run_file(
    version: int, model: str, *, repeats: int = 5
) -> tuple[int, int, list[tuple[str, list[str]]], dict[str, int]]:
    source = ROOT / f"Test_data_generating_{version}.json"
    destination = ROOT / f"Test_data_generating_{version}_results.text"
    raw = json.loads(source.read_text(encoding="utf-8"))
    cases = flatten_cases(raw, version)
    passed = failed = 0
    rows: list[dict] = []
    stability = {"clean": 0, "flaky": 0, "always": 0}

    for index, case in enumerate(cases, 1):
        if index > 1:
            time.sleep(8.0)
        runs: list[dict] = []
        for run_index in range(1, repeats + 1):
            if run_index > 1:
                time.sleep(2.0)
            run = _run_case_once(case)
            runs.append(run)
            warn_bit = f" CLAIM {run['warnings'][0]}" if run["warnings"] else ""
            print(
                f"v{version} [{index}/{len(cases)}] "
                f"run {run_index}/{repeats} "
                f"{'PASS' if run['ok'] else 'FAIL'} {case.get('id')} "
                f"({run['ms']}ms) {run['issues'][:2]}{warn_bit}",
                flush=True,
            )
        row = _aggregate_case_runs(case, runs, repeats)
        rows.append(row)
        passed += int(row["ok"])
        failed += int(not row["ok"])
        stability[row["claim_stability"]] += 1
        print(
            f"v{version} [{index}/{len(cases)}] AGG {case.get('id')}: "
            f"pass {row['pass_count']}/{repeats}, "
            f"claim-issues {row['runs_with_claim_issues']}/{repeats} "
            f"({row['claim_stability']})",
            flush=True,
        )

    lines = [
        f"Thoth Generate/Rewrite Test Results — {source.name}",
        f"Writing model: {model}",
        f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Repeats per case: {repeats}",
        f"Summary: {passed}/{passed + failed} cases passed all {repeats} runs "
        f"({failed}/{passed + failed} had at least one hard fail)",
        (
            f"Claim stability: {stability['clean']} clean (0/{repeats} with issues), "
            f"{stability['flaky']} flaky (some runs), "
            f"{stability['always']} always ({repeats}/{repeats} with issues)"
        ),
        "",
    ]
    for row in rows:
        finding_lines = []
        if row["finding_counts"]:
            # Problems first, then restatement/grounded; group by frequency desc.
            order = {"fabricated": 0, "missing": 1, "restatement": 2, "grounded": 3}

            def _sort_key(item: tuple[str, int]) -> tuple:
                line, count = item
                kind = 9
                for name, rank in order.items():
                    if f"[{name}]" in line:
                        kind = rank
                        break
                return (kind, -count, line)

            for line, count in sorted(row["finding_counts"].items(), key=_sort_key):
                finding_lines.append(f"{line}  — {count}/{repeats}")
        else:
            finding_lines.append("  (no concrete claims extracted)")

        example_note = (
            "from a run with flagged findings"
            if row["example_from_flagged"]
            else "no flagged run; showing first run"
        )
        lines += [
            f"[pass {row['pass_count']}/{repeats}] {row.get('id')} — "
            f"{row.get('scenario')} ({row.get('feature')})",
            f"Settings: {json.dumps(row.get('settings') or {}, ensure_ascii=False)}",
            f"Avg duration: {row['avg_ms']} ms | "
            f"Claim-issue runs: {row['runs_with_claim_issues']}/{repeats} "
            f"({row['claim_stability']})",
            f"Hard-fail issues seen: "
            f"{'; '.join(row['issues_union']) if row['issues_union'] else 'None'}",
            "Claim findings (count of runs where the finding appeared):",
            *finding_lines,
            f"Example output ({example_note}):",
            str(row["example_output"]),
            "",
            "-" * 80,
            "",
        ]

    lines += [
        "======== CLAIM STABILITY TOTALS ========",
        f"Clean (zero claim issues in any of {repeats} runs): {stability['clean']}",
        f"Flaky (issues in some but not all runs): {stability['flaky']}",
        f"Always (issues in every run): {stability['always']}",
        "",
    ]
    destination.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {destination} — {passed}/{passed + failed}", flush=True)
    print(
        f"Claim stability v{version}: clean={stability['clean']} "
        f"flaky={stability['flaky']} always={stability['always']}",
        flush=True,
    )
    fails = [
        (str(row.get("id")), row["issues_union"])
        for row in rows
        if not row["ok"]
    ]
    return passed, failed, fails, stability


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--versions",
        default="2-9",
        help="Comma list or range like 2-9 / 4,5,8",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Run each case N times with the same input (default: 5)",
    )
    args = parser.parse_args()
    repeats = max(1, int(args.repeats))
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
    print(f"Repeats per case: {repeats}", flush=True)

    summary: list[tuple[int, int, int]] = []
    all_fails: list[tuple[int, str, list[str]]] = []
    total_stability = {"clean": 0, "flaky": 0, "always": 0}
    for version in versions:
        path = ROOT / f"Test_data_generating_{version}.json"
        if not path.exists():
            continue
        print(f"\n===== {path.name} ({model}) =====", flush=True)
        passed, failed, fails, stability = run_file(
            version, model, repeats=repeats
        )
        summary.append((version, passed, failed))
        all_fails.extend((version, case_id, issues) for case_id, issues in fails)
        for key in total_stability:
            total_stability[key] += stability[key]

    print("\n======== OVERALL ========", flush=True)
    total_pass = total_fail = 0
    for version, passed, failed in summary:
        print(f"v{version}: {passed}/{passed + failed} cases passed all {repeats} runs", flush=True)
        total_pass += passed
        total_fail += failed
    print(
        f"TOTAL: {total_pass}/{total_pass + total_fail} cases passed all "
        f"{repeats} runs on {model}",
        flush=True,
    )
    print(
        f"Claim stability across all cases: "
        f"clean={total_stability['clean']} "
        f"flaky={total_stability['flaky']} "
        f"always={total_stability['always']}",
        flush=True,
    )
    if all_fails:
        print("\nFailures (hard-fail in at least one run):", flush=True)
        for version, case_id, issues in all_fails:
            print(f"  v{version} {case_id}: {issues[:3]}", flush=True)

    summary_path = ROOT / f"Test_data_generating_{model.replace(':', '_').replace('/', '_')}_summary.text"
    summary_path.write_text(
        "\n".join(
            [
                "Generate/Rewrite matrix summary (repeat-run mode)",
                f"Model: {model}",
                f"Repeats per case: {repeats}",
                f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"Total: {total_pass}/{total_pass + total_fail} cases passed all {repeats} runs",
                (
                    f"Claim stability: clean={total_stability['clean']} "
                    f"flaky={total_stability['flaky']} "
                    f"always={total_stability['always']}"
                ),
                "",
                *[
                    f"v{version}: {passed}/{passed + failed}"
                    for version, passed, failed in summary
                ],
                "",
                "Failures:" if all_fails else "No hard failures.",
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
