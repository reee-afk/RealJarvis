"""
The six tools. Every function returns {"spoken": str, "card": dict}.

Guardrails baked in here, not just described elsewhere:
- Never invent a number, date, filename or client — every claim below is
  read straight out of a vault file or memory file, or the tool says it
  doesn't know.
- research_web never spends money and never calls a paid API.
- read_inbox is read-only; nothing here ever sends anything.
"""
import html
import imaplib
import email as email_lib
import os
import re
import urllib.request
import urllib.parse
from datetime import date, datetime
from html.parser import HTMLParser

from . import memory, vault

AMOUNT_RE = re.compile(r"([₹£$])\s?([\d,]+)")
DUE_RE = re.compile(r"Due:\s*([\d-]+)")
STATUS_RE = re.compile(r"Status:\s*(\w+)")
CLIENT_LINK_RE = re.compile(r"Client:\s*\[\[([^\]]+)\]\]")


def _short(path: str) -> str:
    """Filename only, for spoken citations."""
    return path.rsplit("/", 1)[-1]


# ---------------------------------------------------------------- search_brain
def search_brain(query: str) -> dict:
    results = vault.search(query, limit=5)
    if not results:
        return {
            "spoken": f"Nothing in your files matches that, sir.",
            "card": {"tool": "search_brain", "query": query, "results": []},
        }
    top = results[0]
    files = [_short(r["path"]) for r in results[:3]]
    if len(results) == 1:
        spoken = f"Found it in {files[0]}, sir: {top['snippet']}"
    else:
        spoken = f"Pulled that from {len(files)} files — {', '.join(files)}, sir."
    return {
        "spoken": spoken,
        "card": {"tool": "search_brain", "query": query, "results": results},
    }


# ---------------------------------------------------------------- research_web
class _DDGParser(HTMLParser):
    """Pulls result titles + snippets out of DuckDuckGo's HTML-only endpoint."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._in_snippet = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "a" and "result__snippet" in (attrs_d.get("class") or ""):
            self._in_snippet = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_snippet:
            self._in_snippet = False
            text = html.unescape("".join(self._buf)).strip()
            if text:
                self.results.append(text)

    def handle_data(self, data_):
        if self._in_snippet:
            self._buf.append(data_)


def _relevant_service_prices(query: str) -> list[dict]:
    haven = vault.search(query + " haven-services", limit=1)
    matches = []
    q_terms = set(re.findall(r"[a-z]+", query.lower()))
    for node in vault.get_index()["nodes"]:
        if "haven-services" not in node["path"].lower():
            continue
        for line in node["content"].splitlines():
            if line.startswith("|") and any(t in line.lower() for t in q_terms):
                matches.append(line)
    return matches[:2]


def research_web(query: str) -> dict:
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (JARVIS/1.0)"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return {
            "spoken": "Web research is unreachable from here right now, sir — network's blocked or down.",
            "card": {"tool": "research_web", "query": query, "error": str(exc)},
        }

    parser = _DDGParser()
    parser.feed(body)
    if not parser.results:
        return {
            "spoken": f"Came up empty searching for that, sir.",
            "card": {"tool": "research_web", "query": query, "results": []},
        }

    finding = parser.results[0]
    price_lines = _relevant_service_prices(query)
    card = {"tool": "research_web", "query": query, "results": parser.results[:3], "your_pricing": price_lines}

    if price_lines:
        spoken = f"{finding} For reference, your own catalog has: {price_lines[0].strip('| ').split('|')[0].strip()}."
    else:
        spoken = finding
    return {"spoken": spoken, "card": card}


# ---------------------------------------------------------------- read_inbox
def _imap_configured() -> bool:
    return bool(os.environ.get("EMAIL_IMAP_HOST") and os.environ.get("EMAIL_USER") and os.environ.get("EMAIL_PASSWORD"))


def read_inbox(unread_only: bool = True) -> dict:
    if not _imap_configured():
        return {
            "spoken": "Inbox isn't connected, sir — no EMAIL_IMAP_HOST in .env yet.",
            "card": {"tool": "read_inbox", "configured": False, "messages": []},
        }
    try:
        host = os.environ["EMAIL_IMAP_HOST"]
        conn = imaplib.IMAP4_SSL(host)
        conn.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASSWORD"])
        conn.select("INBOX", readonly=True)
        criterion = "UNSEEN" if unread_only else "ALL"
        status, data_ = conn.search(None, criterion)
        ids = data_[0].split()[-10:]
        messages = []
        vault_text = " ".join(n["content"].lower() for n in vault.get_index()["nodes"])
        for msg_id in ids:
            status, msg_data = conn.fetch(msg_id, "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])
            sender = email_lib.utils.parseaddr(msg.get("From", ""))[1]
            subject = msg.get("Subject", "(no subject)")
            known = sender.split("@")[0].lower() in vault_text if sender else False
            messages.append({"from": sender, "subject": subject, "known_client": known})
        conn.logout()
        known_count = sum(1 for m in messages if m["known_client"])
        spoken = f"{len(messages)} unread, sir — {known_count} from people already in your files." if messages else "Inbox is clear, sir."
        return {"spoken": spoken, "card": {"tool": "read_inbox", "configured": True, "messages": messages}}
    except Exception as exc:
        return {
            "spoken": "Couldn't reach the inbox just now, sir.",
            "card": {"tool": "read_inbox", "configured": True, "error": str(exc)},
        }


# ---------------------------------------------------------------- invoices helper
def _parse_invoices() -> list[dict]:
    out = []
    for node in vault.get_index()["nodes"]:
        if node["type"] != "invoices":
            continue
        content = node["content"]
        amt = AMOUNT_RE.search(content)
        due = DUE_RE.search(content)
        status = STATUS_RE.search(content)
        client = CLIENT_LINK_RE.search(content)
        if not (amt and due and status):
            continue
        try:
            due_date = datetime.strptime(due.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        out.append(
            {
                "title": node["title"],
                "path": node["path"],
                "client": client.group(1) if client else None,
                "currency": amt.group(1),
                "amount": int(amt.group(2).replace(",", "")),
                "due": due_date,
                "status": status.group(1).lower(),
                "overdue": due_date < date.today() and status.group(1).lower() != "paid",
            }
        )
    return out


# ---------------------------------------------------------------- brief_me
def brief_me() -> dict:
    inbox = read_inbox(unread_only=True)
    invoices = _parse_invoices()
    overdue = [i for i in invoices if i["overdue"]]
    overdue.sort(key=lambda i: i["amount"], reverse=True)

    parts = []
    if inbox["card"].get("configured"):
        n = len(inbox["card"].get("messages", []))
        parts.append(f"{n} unread")
    else:
        parts.append("inbox not connected")
    if overdue:
        parts.append(f"{len(overdue)} overdue invoice{'s' if len(overdue) != 1 else ''}")
    parts.append("calendar not connected")

    spoken = "Morning brief, sir: " + "; ".join(parts) + "."
    card = {
        "tool": "brief_me",
        "inbox": inbox["card"],
        "overdue_invoices": [{**i, "due": i["due"].isoformat()} for i in overdue],
        "calendar_connected": False,
    }
    return {"spoken": spoken, "card": card}


# ---------------------------------------------------------------- remember
def remember(fact: str) -> dict:
    path = memory.remember(fact)
    return {
        "spoken": f"Noted, sir. I wrote: \"{fact.strip()}\" to {path.name}.",
        "card": {"tool": "remember", "fact": fact.strip(), "file": path.name},
    }


# ---------------------------------------------------------------- plan_day
def plan_day() -> dict:
    invoices = _parse_invoices()
    items = []
    for inv in invoices:
        if inv["status"] == "paid":
            continue
        weight = inv["amount"] * (2 if inv["overdue"] else 1) * (1 if inv["status"] == "unpaid" else 0.6)
        label = f"Chase {inv['client'] or 'invoice'} — {inv['currency']}{inv['amount']:,} {inv['status']}"
        if inv["overdue"]:
            label += f" (overdue since {inv['due'].isoformat()})"
        items.append((weight, label, inv["path"]))

    for node in vault.get_index()["nodes"]:
        if node["type"] == "notes" and "follow" in node["title"].lower():
            for line in node["content"].splitlines():
                line = line.strip()
                if line.startswith("- "):
                    items.append((5000, line[2:], node["path"]))

    items.sort(key=lambda t: t[0], reverse=True)
    top5 = items[:5]
    if not top5:
        return {
            "spoken": "Nothing urgent queued, sir — clean plate.",
            "card": {"tool": "plan_day", "items": []},
        }
    spoken = f"Top of the list, sir: {top5[0][1]}." + (f" {len(top5) - 1} more behind it." if len(top5) > 1 else "")
    card = {"tool": "plan_day", "items": [{"label": t[1], "source": _short(t[2])} for t in top5]}
    return {"spoken": spoken, "card": card}


TOOLS = {
    "search_brain": search_brain,
    "research_web": research_web,
    "read_inbox": read_inbox,
    "brief_me": brief_me,
    "remember": remember,
    "plan_day": plan_day,
}
