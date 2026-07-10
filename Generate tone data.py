"""
Generates tone-rewrite training pairs via Groq API (default).

Never put your API key in this file. Set it in the environment:
  export GROQ_API_KEY=your_key_here

Match grammar quantity (recommended before fine-tuning):
  python3 "Generate tone data.py" --match-grammar --skip-tone-check

Other examples:
  python3 "Generate tone data.py" --grammar-count 19434
  python3 "Generate tone data.py" --target-count 800 --append
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
TEST_DATA = ROOT / "test_data"
TRAIN_DATA_PATH = ROOT / "train_data.jsonl"
SEED_FILE = TEST_DATA / "Tone rewrite training data .json"
TONES_FILE = ROOT / "extension" / "generate_tones.json"
DEFAULT_OUTPUT_FILE = TEST_DATA / "tone_rewrite_generated.jsonl"

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_REQUEST_DELAY_SEC = 0.35
DEFAULT_TARGET_COUNT = 500
DEFAULT_TONE_RATIO = 0.20
SIMILARITY_REJECT_THRESHOLD = 0.85
MAX_ATTEMPTS_MULTIPLIER = 4
MAX_RATE_LIMIT_RETRIES = 5

SEED_SENTENCES = [
    "Can you send me the file when you get a chance?",
    "The meeting is at 3pm tomorrow.",
    "I finished the project early.",
    "We need to talk about the budget.",
    "Thanks for your help yesterday.",
    "The flight got delayed by two hours.",
    "I think we should change the design.",
    "Please review this before Friday.",
    "The package should arrive next week.",
    "I'm not sure if this plan will work.",
    "We ran out of time during the call.",
    "The client asked for more details.",
    "I forgot to bring the documents.",
    "Let's reschedule the appointment.",
    "The numbers look off this month.",
    "I appreciate you covering for me.",
    "The new software update caused some issues.",
    "We should follow up with the vendor.",
    "I have a few questions about the contract.",
    "The team worked hard on this launch.",
    "Can we move the call to next week?",
    "I noticed a typo in the document.",
    "The results were better than expected.",
    "Please let me know if you need anything.",
    "We lost an important client this week.",
    "I'm working on the presentation now.",
    "The server crashed last night.",
    "Thanks for being patient with the delays.",
    "I'd like to request some time off.",
    "The report is almost ready.",
    "We should double check these figures.",
    "I missed the email you sent earlier.",
    "The interview went well.",
    "Could you double check this for me?",
    "Our supplier raised their prices.",
    "I think we found the bug.",
    "The training session is next Thursday.",
    "We're behind on this task.",
    "I wanted to share some quick feedback.",
    "The new hire starts on Monday.",
    "Please send the updated invoice.",
    "I think we should cancel the event.",
    "The product launch went smoothly.",
    "We need another round of testing.",
    "I appreciate your quick response.",
    "The deadline got pushed up a week.",
    "Let's plan the next steps together.",
    "I had to leave the meeting early.",
    "The customer left a complaint.",
    "We should celebrate this win.",
]

def _load_tones() -> list[str]:
    if TONES_FILE.is_file():
        try:
            data = json.loads(TONES_FILE.read_text(encoding="utf-8"))
            tones = data.get("tones")
            if isinstance(tones, list) and tones:
                return [str(tone).strip() for tone in tones if str(tone).strip()]
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return list(_DEFAULT_TONES)


_DEFAULT_TONES = [
    "aggressive", "blunt and forceful", "harsh and direct",
    "friendly", "warm and friendly", "extra friendly",
    "formal", "very formal", "businesslike",
    "casual", "relaxed and casual", "laid-back",
    "simple, easy to understand words", "very simple language",
    "sophisticated, advanced vocabulary", "elevated and refined",
    "enthusiastic", "excited and energetic",
    "polite", "very polite and courteous",
    "sympathetic", "compassionate and gentle",
    "urgent", "very urgent and time-sensitive",
    "confident", "assertive and self-assured",
    "apologetic", "sincere and apologetic",
    "persuasive", "convincing and compelling",
    "concise", "short and to the point",
    "diplomatic", "tactful",
    "encouraging", "supportive and uplifting",
    "sarcastic", "dry and sarcastic",
    "humorous", "playful and lighthearted",
    "grateful",     "deeply appreciative",
]

TONES = _load_tones()

WRAPPERS = [
    "Rewrite this text to sound {tone}. You can change word choice, structure, and length as needed to fully achieve this tone. Return only the rewritten text, nothing else.\n\n{source}",
    "Make this text sound {tone}. Feel free to restructure sentences and change wording as much as needed. Return only the rewritten text, nothing else.\n\n{source}",
    "Change the tone of this text to {tone}. Rewrite it as much as needed to fully match this tone. Return only the rewritten text, nothing else.\n\n{source}",
]

PREAMBLE_PATTERNS = [
    r"^(sure|okay|ok|certainly|of course|absolutely)[,!.]?\s*",
    r"^here'?s?( is)?( the)?( rewritten)?( version)?( text)?[:.]?\s*",
    r"^(rewritten( text)?|result|output|answer)[:.]?\s*",
]


def clean_completion(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```\w*\n?|```$", "", text).strip()
    if len(text) >= 2 and text[0] in "\"'" and text[-1] in "\"'":
        text = text[1:-1].strip()
    for pattern in PREAMBLE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def call_groq(prompt: str, model: str, *, temperature: float = 0.8, api_key: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    delay = 2
    for _ in range(MAX_RATE_LIMIT_RETRIES):
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code in (401, 403):
            raise RuntimeError(
                "Groq API rejected the key (401 Unauthorized). "
                "Check GROQ_API_KEY — create a new key at https://console.groq.com/keys "
                "and run: export GROQ_API_KEY=gsk_..."
            )
        if resp.status_code == 429:
            print(f"  rate limited, waiting {delay}s...")
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
        if GROQ_REQUEST_DELAY_SEC > 0:
            time.sleep(GROQ_REQUEST_DELAY_SEC)
        return resp.json()["choices"][0]["message"]["content"].strip()
    raise RuntimeError("Groq rate limit retries exhausted, try again later")


def verify_groq_api_key(api_key: str) -> None:
    """Fail fast before a long run if the API key is missing or invalid."""
    api_key = api_key.strip()
    if not api_key:
        raise SystemExit("GROQ_API_KEY is empty.")
    if not api_key.startswith("gsk_"):
        print("Warning: Groq keys usually start with gsk_ — double-check your key.")

    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(
        "https://api.groq.com/openai/v1/models",
        headers=headers,
        timeout=30,
    )
    if resp.status_code in (401, 403):
        raise SystemExit(
            "Groq API key is invalid or expired (401 Unauthorized).\n"
            "1. Open https://console.groq.com/keys\n"
            "2. Create a new API key\n"
            "3. In this terminal run: export GROQ_API_KEY=gsk_your_new_key\n"
            "4. Re-run the generator"
        )
    resp.raise_for_status()
    print("Groq API key verified.")


def call_ollama(prompt: str, model: str, temperature: float = 0.8) -> str:
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def call_model(prompt: str, args: argparse.Namespace, temperature: float = 0.8) -> str:
    if args.provider == "groq":
        return call_groq(prompt, args.model, temperature=temperature, api_key=args.api_key)
    return call_ollama(prompt, args.model, temperature=temperature)


def too_similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() > SIMILARITY_REJECT_THRESHOLD


def pair_key(pair: dict[str, str]) -> tuple[str, str]:
    prompt = pair.get("prompt", "")
    source = prompt.rsplit("\n\n", 1)[-1].strip().lower() if "\n\n" in prompt else ""
    return source, str(pair.get("completion") or "").strip().lower()


def load_existing_pairs(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    pairs: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("prompt") and row.get("completion"):
                pairs.append(row)
    return pairs


def load_seed_sentences_from_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    sentences: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            prompt = str(row.get("prompt") or "")
            if "\n\n" in prompt:
                sentences.append(prompt.rsplit("\n\n", 1)[-1].strip())
    return sentences


def count_grammar_rows(path: Path = TRAIN_DATA_PATH) -> int | None:
    if not path.is_file():
        return None
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("task") or "") == "grammar":
                count += 1
    return count


def count_hand_tone_pairs() -> int:
    total = 0
    if not SEED_FILE.is_file():
        return 0
    with SEED_FILE.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("prompt") and row.get("completion"):
                total += 1
    return total


def passes_tone_check(args: argparse.Namespace, text: str, tone: str) -> bool:
    check_prompt = (
        f'Does the following text sound {tone}? Answer with only the single '
        f'word "yes" or "no".\n\n{text}'
    )
    try:
        answer = call_model(check_prompt, args, temperature=0.0).strip().lower()
    except Exception:
        return True
    return answer.startswith("yes")


def compute_target_count(grammar_count: int | None, tone_ratio: float, fallback: int) -> int:
    if grammar_count is None:
        return fallback
    return max(1, int(round((tone_ratio * grammar_count) / (1 - tone_ratio))))


def write_pairs(path: Path, pairs: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate tone-rewrite training pairs (Groq API by default)."
    )
    parser.add_argument(
        "--provider", choices=["groq", "ollama"], default="groq",
        help="Generation backend (default: groq API)",
    )
    parser.add_argument("--model", default=None, help="Model name")
    parser.add_argument("--api-key", default=None, help="Groq API key (or GROQ_API_KEY env)")
    parser.add_argument("--grammar-count", type=int, default=None)
    parser.add_argument("--tone-ratio", type=float, default=DEFAULT_TONE_RATIO)
    parser.add_argument("--target-count", type=int, default=None)
    parser.add_argument(
        "--match-grammar", action="store_true",
        help="Generate enough tone pairs to 1:1 match grammar rows in train_data.jsonl",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--append", action="store_true")
    parser.add_argument(
        "--skip-tone-check", action="store_true",
        help="Skip yes/no tone verification (recommended for large batches)",
    )
    args = parser.parse_args()

    if args.model is None:
        args.model = DEFAULT_GROQ_MODEL if args.provider == "groq" else DEFAULT_OLLAMA_MODEL

    if args.provider == "groq":
        args.api_key = (args.api_key or os.environ.get("GROQ_API_KEY") or "").strip()
        if not args.api_key:
            raise SystemExit(
                "No Groq API key. Run: export GROQ_API_KEY=your_key_here\n"
                "Get a free key at https://console.groq.com/keys"
            )
        verify_groq_api_key(args.api_key)

    grammar_count = args.grammar_count or count_grammar_rows()
    if grammar_count is not None:
        print(f"Grammar rows: {grammar_count:,}")

    if args.match_grammar:
        if grammar_count is None:
            raise SystemExit(
                "Need train_data.jsonl or --grammar-count. Run: .venv/bin/python prepare_data.py --skip-c4"
            )
        hand_pairs = count_hand_tone_pairs()
        total_target = max(0, grammar_count - hand_pairs)
        print(
            f"--match-grammar: {hand_pairs:,} curated pairs on disk → "
            f"generate {total_target:,} via API"
        )
    else:
        total_target = args.target_count or compute_target_count(
            grammar_count, args.tone_ratio, DEFAULT_TARGET_COUNT
        )

    output_path = Path(args.output)
    pairs = load_existing_pairs(output_path) if args.append else []
    seen = {pair_key(p) for p in pairs}
    new_target = max(0, total_target - len(pairs)) if args.append else total_target

    seed_sentences = list(SEED_SENTENCES)
    seed_sentences.extend(load_seed_sentences_from_file(SEED_FILE))
    seed_sentences = list(dict.fromkeys(s for s in seed_sentences if s.strip()))

    print(f"Provider: {args.provider}, model: {args.model}")
    print(f"Output: {output_path}")
    print(f"Target: {new_target:,} new pairs ({total_target:,} total)")

    if new_target == 0:
        print("Nothing to generate.")
        return

    all_combos = [(s, t) for s in seed_sentences for t in TONES]
    random.shuffle(all_combos)

    attempts = 0
    combo_index = 0
    generated = 0
    max_attempts = new_target * MAX_ATTEMPTS_MULTIPLIER

    while generated < new_target and attempts < max_attempts:
        if combo_index >= len(all_combos):
            random.shuffle(all_combos)
            combo_index = 0

        source, tone = all_combos[combo_index]
        combo_index += 1
        attempts += 1

        wrapper = random.choice(WRAPPERS)
        prompt = wrapper.format(tone=tone, source=source)

        try:
            raw_completion = call_model(prompt, args)
        except RuntimeError as exc:
            if "401 Unauthorized" in str(exc):
                raise SystemExit(str(exc)) from exc
            print(f"[{attempts}] skip, request failed: {exc}")
            continue
        except Exception as exc:
            print(f"[{attempts}] skip, request failed: {exc}")
            continue

        completion = clean_completion(raw_completion)
        if not completion:
            print(f"[{attempts}] skip, empty")
            continue
        if too_similar(source, completion):
            print(f"[{attempts}] skip, too similar")
            continue
        if not args.skip_tone_check and not passes_tone_check(args, completion, tone):
            print(f"[{attempts}] skip, tone check failed ({tone})")
            continue

        candidate = {"prompt": prompt, "completion": completion}
        key = pair_key(candidate)
        if key in seen:
            continue

        seen.add(key)
        pairs.append(candidate)
        generated += 1
        print(f"[{len(pairs)}/{total_target}] kept ({tone}): {completion[:60]}...")

        if generated % 10 == 0:
            write_pairs(output_path, pairs)

    write_pairs(output_path, pairs)
    print(f"\nDone. {len(pairs):,} pairs → {output_path} ({generated:,} new, {attempts} attempts)")
    print(
        "Next: .venv/bin/python prepare_data.py --skip-c4 --tone-balanced && "
        ".venv/bin/python scripts/finetune_grammar_lora.py --prepare-only"
    )


if __name__ == "__main__":
    main()
