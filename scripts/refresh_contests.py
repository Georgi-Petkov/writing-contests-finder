#!/usr/bin/env python3
"""Refresh the inspirational-writing contest list.

Searches the web (via the Claude API's web_search tool) for open/upcoming
inspirational-writing contests in English and Bulgarian, merges newly found
contests into data/contests.json (matched by contest name, not URL — several
Bulgarian contests are sourced from the same aggregator roundup article and
would otherwise collide), recomputes each contest's status from its deadline,
and regenerates the embedded data block in live-site/content/index.html.

Usage:
    export ANTHROPIC_API_KEY=...
    python scripts/refresh_contests.py
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

import anthropic

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "contests.json"
INDEX_HTML_PATH = REPO_ROOT / "live-site" / "content" / "index.html"

MODEL = "claude-sonnet-5"

STATUS_RANK = {"open": 0, "upcoming": 1, "closed": 2}

CONTEST_SCHEMA = {
    "type": "object",
    "properties": {
        "contests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Short, unique, kebab-case slug for this contest (e.g. 'reedsy-essay-2027').",
                    },
                    "name": {"type": "string"},
                    "url": {
                        "type": "string",
                        "description": "Canonical URL to the contest's own official page (not an aggregator listing), if one exists.",
                    },
                    "language": {"type": "string", "enum": ["EN", "BG"]},
                    "topic": {"type": "string", "description": "Theme/genre, in plain language."},
                    "prize": {"type": "string"},
                    "format": {
                        "type": "string",
                        "description": "Word/page limits, eligibility restrictions (age, nationality, etc.). Entry fee goes in fee_free/fee_amount instead, not here.",
                    },
                    "fee_free": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "true = free to enter, false = has an entry fee, null = the source doesn't state one — do not guess.",
                    },
                    "fee_amount": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "The fee figure when there is one (e.g. '$12', '€20 (or €10 for students)'), null when free or unknown.",
                    },
                    "opens": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "ISO date (YYYY-MM-DD) the contest opens, or null if not stated / already open.",
                    },
                    "deadline": {
                        "type": "string",
                        "description": "ISO date (YYYY-MM-DD) if known precisely; otherwise a short human-readable string noting the uncertainty.",
                    },
                    "reprint_policy": {
                        "type": "string",
                        "enum": ["yes", "no", "unclear"],
                        "description": (
                            "Whether previously-published/reused work is allowed. "
                            "'yes' = reuse/adaptation OK (low time investment). "
                            "'no' = must be original/unpublished (needs fresh writing). "
                            "'unclear' = the source doesn't state a policy either way — do not guess."
                        ),
                    },
                    "reprint_note": {
                        "type": "string",
                        "description": "One or two sentences explaining the reprint_policy value, in plain language.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "upcoming", "closed"],
                        "description": "Best guess at submission status as of today; the page recomputes this from the deadline anyway.",
                    },
                },
                "required": [
                    "id", "name", "url", "language", "topic", "prize", "format",
                    "fee_free", "fee_amount", "opens", "deadline",
                    "reprint_policy", "reprint_note", "status",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["contests"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are researching writing contests for an inspirational-writing tracker. Cast a wide \
genre net: inspirational/motivational essays, personal narrative and memoir, uplifting \
poetry, faith/self-help-adjacent writing, and open-theme literary contests a writer in \
this space could adapt to.

Search BOTH languages:
- English: check contest aggregators such as Reedsy, Poets & Writers (pw.org/grants), \
Winning Writers, the "Writing Deadlines" Substack, and freedomwithwriting.com, then follow \
through to each contest's own official page for exact details.
- Bulgarian: there is no fixed source list — search from scratch each time (e.g. \
konkurs-bg.com, litdesign-bg.com's "Конкурсен глас" roundups, bukvite.bg, Bulgarian \
читалища and cultural foundations) and follow through to official pages where possible.

For every contest, report the reprint_policy field honestly: if the source doesn't state \
whether previously-published or reused work is allowed, use "unclear" — do not guess. This \
field is not a filter; it tells the writer whether she can adapt existing work (fast) or \
needs to write something new (slower), so getting "unclear" right matters more than forcing \
a yes/no.

Report the entry fee the same honest way: set fee_free to true or false only when the \
source actually states it, and leave it null (with fee_amount null too) when the source is \
silent — don't assume a contest is free just because no fee was mentioned in a short listing.

Only include contests that are currently open, opening soon, or closed within roughly the \
last month (so the merge step can correctly mark them as recently closed rather than losing \
them entirely). Skip anything long expired with no sign of a recurring next edition.
"""


def build_user_prompt(existing_contests: list[dict]) -> str:
    existing_urls = sorted({c["url"] for c in existing_contests if c.get("url")})
    return (
        "Here are the contest URLs already in the tracker (for context — search for "
        "NEW or UPDATED contests, you don't need to re-report ones that haven't changed):\n"
        + "\n".join(f"- {u}" for u in existing_urls)
        + "\n\nSearch for open, upcoming, and recently-closed inspirational-writing "
        "contests in English and Bulgarian. Report every contest you find (new ones "
        "and any of the above whose details have changed) as structured output."
    )


def normalize_name(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s)
    return s


def dedupe_key(contest: dict) -> tuple:
    # Matched by (language, normalized name) rather than URL: several Bulgarian
    # contests are only reachable via the same aggregator roundup article, so a
    # URL-based key would silently collapse distinct contests into one.
    return (contest.get("language", ""), normalize_name(contest.get("name", "")))


def parse_iso_date(value: str | None):
    if not value:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return None
    try:
        return date(*(int(g) for g in match.groups()))
    except ValueError:
        return None


def recompute_status(contest: dict, today: date) -> str:
    deadline = parse_iso_date(contest.get("deadline"))
    opens = parse_iso_date(contest.get("opens"))
    if deadline is None:
        return contest.get("status", "open")
    if deadline < today:
        return "closed"
    if opens and opens > today:
        return "upcoming"
    return "open"


def fetch_new_contests(existing_contests: list[dict]) -> list[dict]:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
        output_config={"format": {"type": "json_schema", "schema": CONTEST_SCHEMA}},
        messages=[{"role": "user", "content": build_user_prompt(existing_contests)}],
    )

    if response.stop_reason == "refusal":
        print("Model declined the request; keeping existing data unchanged.", file=sys.stderr)
        return []

    if response.stop_reason == "pause_turn":
        # Server-side web search hit its iteration cap; resume once.
        follow_up = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
            output_config={"format": {"type": "json_schema", "schema": CONTEST_SCHEMA}},
            messages=[
                {"role": "user", "content": build_user_prompt(existing_contests)},
                {"role": "assistant", "content": response.content},
            ],
        )
        response = follow_up

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        print("No structured output returned; keeping existing data unchanged.", file=sys.stderr)
        return []

    parsed = json.loads(text)
    return parsed.get("contests", [])


def merge_contests(existing: list[dict], found: list[dict]) -> list[dict]:
    by_key = {dedupe_key(c): c for c in existing if c.get("name")}
    for contest in found:
        if not contest.get("name"):
            continue
        by_key[dedupe_key(contest)] = contest

    today = date.today()
    merged = list(by_key.values())
    for contest in merged:
        contest["status"] = recompute_status(contest, today)

    merged.sort(
        key=lambda c: (
            STATUS_RANK.get(c["status"], 1),
            c.get("deadline") or "9999-99-99",
        )
    )
    return merged


def write_data_file(contests: list[dict]) -> dict:
    payload = {"generated_at": date.today().isoformat(), "contests": contests}
    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def regenerate_index_html(payload: dict) -> None:
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    new_block = json.dumps(payload, ensure_ascii=False, indent=2)
    updated, count = re.subn(
        r'(<script type="application/json" id="contest-data">\n).*?(\n</script>)',
        lambda m: m.group(1) + new_block + m.group(2),
        html,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one contest-data script block in {INDEX_HTML_PATH}, found {count}"
        )
    INDEX_HTML_PATH.write_text(updated, encoding="utf-8")


def main() -> None:
    existing = json.loads(DATA_PATH.read_text(encoding="utf-8"))["contests"]
    found = fetch_new_contests(existing)
    merged = merge_contests(existing, found)
    payload = write_data_file(merged)
    regenerate_index_html(payload)
    print(f"Wrote {len(merged)} contests ({len(found)} newly found/updated this run).")


if __name__ == "__main__":
    main()
