"""
Decides conversation vs. tool, with or without a model.

If ANTHROPIC_API_KEY is set, Claude does the routing and the small talk.
If not, a keyword/content-overlap heuristic does — and every reply says so,
per the "routing must work without a model, and never pass off keyword
matching as the model talking" rule.
"""
import json
import os
import re
import urllib.request
import urllib.error
from collections import deque
from pathlib import Path

from . import tools, vault

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_LIMIT = 10
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

_history = deque(maxlen=HISTORY_LIMIT)
_last_tool = {"name": None, "args": None}

GREETING_RE = re.compile(r"^\s*(hi|hello|hey|yo|hiya|sup|good (morning|evening|afternoon))\b", re.I)
SMALLTALK_RE = re.compile(
    r"^\s*(how (are|'re) you|can you hear me|what do you think|thanks|thank you|"
    r"you (there|awake)|are you (there|working)|bye|goodnight|good night)\b",
    re.I,
)
FOLLOWUP_RE = re.compile(
    r"^\s*(why\??|why('| i)?s that\??|what about (the )?(second|third|first|next|that)( one)?\??|"
    r"go on\.?|and\??|tell me more\.?|anything else\??)\s*$",
    re.I,
)

TOOL_KEYWORDS = {
    "brief_me": ["brief me", "morning brief", "catch me up", "what's on", "whats on", "update me", "daily brief"],
    "plan_day": ["plan my day", "plan the day", "what should i do", "priorit", "top of my list", "plan day"],
    "remember": ["remember that", "remember this", "note that", "don't forget", "dont forget", "make a note"],
    "read_inbox": ["inbox", "unread", "who emailed", "who wrote", "check my mail", "check email"],
    "research_web": ["research", "compare", "market rate", "competitor", "how much do", "look up online", "what does it cost", "price of"],
    "search_brain": ["find", "search", "who is", "what is", "where is", "which client", "look up", "in my notes", "in my files"],
}


def is_llm_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _load(name: str) -> str:
    for path in (BASE_DIR / "agent" / name, BASE_DIR / name):
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def _system_prompt() -> str:
    return _load("prompt.md") + "\n\n" + _load("CLAUDE.md")


def _run_tool(name: str, args: dict) -> dict:
    fn = tools.TOOLS[name]
    result = fn(**args) if args else fn()
    _last_tool["name"] = name
    _last_tool["args"] = args
    return result


def _remember_arg(message: str) -> dict:
    stripped = re.sub(r"^(please\s+)?remember( that| this)?[:,]?\s*", "", message, flags=re.I)
    stripped = re.sub(r"^(please\s+)?(make a note( that)?|note that|don'?t forget( that)?)[:,]?\s*", "", stripped, flags=re.I)
    return {"fact": stripped.strip() or message.strip()}


TOOL_ARG_BUILDERS = {
    "search_brain": lambda msg: {"query": msg},
    "research_web": lambda msg: {"query": msg},
    "read_inbox": lambda msg: {"unread_only": True},
    "brief_me": lambda msg: {},
    "plan_day": lambda msg: {},
    "remember": _remember_arg,
}


# ------------------------------------------------------------- heuristic path
def _heuristic_route(message: str) -> dict:
    text = message.strip()
    low = text.lower()

    if FOLLOWUP_RE.match(low) and _last_tool["name"]:
        name = _last_tool["name"]
        result = _run_tool(name, _last_tool["args"])
        result = {**result, "spoken": "Following up, sir — " + result["spoken"]}
        return {**result, "meta": {"llm": False, "tool": name}}

    if GREETING_RE.match(low) or SMALLTALK_RE.match(low):
        spoken = _smalltalk_reply(low)
        return {"spoken": spoken, "card": {"tool": None, "reply": spoken}, "meta": {"llm": False, "tool": None}}

    best_tool, best_score = None, 0
    for name, kws in TOOL_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in low)
        if score > best_score:
            best_tool, best_score = name, score

    if best_tool:
        args = TOOL_ARG_BUILDERS[best_tool](text)
        result = _run_tool(best_tool, args)
        return {**result, "meta": {"llm": False, "tool": best_tool}}

    # No keyword hit — score the question against the vault itself (spec #6).
    hits = vault.search(text, limit=3)
    if hits:
        result = _run_tool("search_brain", {"query": text})
        return {**result, "meta": {"llm": False, "tool": "search_brain"}}

    spoken = "Not sure what you need there, sir — try rephrasing, or ask me to search, research, brief, or plan."
    return {"spoken": spoken, "card": {"tool": None, "reply": spoken}, "meta": {"llm": False, "tool": None}}


def _smalltalk_reply(low: str) -> str:
    if GREETING_RE.match(low):
        return "Evening, sir. What do you need?" if "evening" in low else "Yes, sir. Go ahead."
    if "hear me" in low or "there" in low or "working" in low or "awake" in low:
        return "Reading you fine, sir."
    if "thank" in low:
        return "Of course, sir."
    if "bye" in low or "night" in low:
        return "Goodnight, sir."
    if "think" in low:
        return "I'd want more to go on before I answer that, sir."
    return "With you, sir."


# ------------------------------------------------------------------- LLM path
TOOL_SCHEMAS = [
    {"name": "search_brain", "description": "A specific fact from Kunal's own files.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "research_web", "description": "Look something up on the web, then land it on Kunal's own numbers.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "read_inbox", "description": "Read-only glance at the inbox.", "input_schema": {"type": "object", "properties": {"unread_only": {"type": "boolean"}}, "required": []}},
    {"name": "brief_me", "description": "Calendar, unread, what slipped.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "remember", "description": "Write one fact to a dated memory file.", "input_schema": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}},
    {"name": "plan_day", "description": "Top 5 items, ordered by what moves money.", "input_schema": {"type": "object", "properties": {}, "required": []}},
]


def _call_claude(messages: list) -> dict:
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    payload = json.dumps(
        {
            "model": model,
            "max_tokens": 400,
            "system": _system_prompt(),
            "messages": messages,
            "tools": TOOL_SCHEMAS,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=payload,
        method="POST",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _llm_route(message: str) -> dict:
    messages = list(_history) + [{"role": "user", "content": message}]
    try:
        resp = _call_claude(messages)
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError) as exc:
        result = _heuristic_route(message)
        result["meta"]["llm_error"] = str(exc)
        return result

    tool_use = next((b for b in resp.get("content", []) if b.get("type") == "tool_use"), None)
    if tool_use:
        name = tool_use["name"]
        args = tool_use.get("input", {})
        if name in tools.TOOLS:
            result = _run_tool(name, args)
            return {**result, "meta": {"llm": True, "tool": name}}

    text_block = next((b for b in resp.get("content", []) if b.get("type") == "text"), None)
    spoken = text_block["text"].strip() if text_block else "Go ahead, sir."
    return {"spoken": spoken, "card": {"tool": None, "reply": spoken}, "meta": {"llm": True, "tool": None}}


# ------------------------------------------------------------------- entrypoint
def handle_message(message: str) -> dict:
    if is_llm_configured():
        result = _llm_route(message)
    else:
        result = _heuristic_route(message)

    _history.append({"role": "user", "content": message})
    tool_name = result["meta"]["tool"]
    summary = result["spoken"] if not tool_name else f"[used {tool_name}] {result['spoken']}"
    _history.append({"role": "assistant", "content": summary})
    return result


def reset_history() -> None:
    _history.clear()
    _last_tool["name"] = None
    _last_tool["args"] = None
