"""Writes to memory/ and nowhere else. One markdown file per remembered fact."""
import re
from datetime import date
from pathlib import Path

from . import data


def _slugify(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())[:max_words]
    slug = "-".join(words) or "note"
    return slug[:60]


def remember(fact: str) -> Path:
    fact = fact.strip()
    today = date.today().isoformat()
    slug = _slugify(fact)
    mem_dir = data.memory_dir()
    path = mem_dir / f"{today}-{slug}.md"
    n = 2
    while path.exists():
        path = mem_dir / f"{today}-{slug}-{n}.md"
        n += 1
    path.write_text(f"# {today}\n\n{fact}\n", encoding="utf-8")
    return path


def all_memories() -> list[dict]:
    mem_dir = data.memory_dir()
    out = []
    for path in sorted(mem_dir.glob("*.md")):
        out.append({"path": str(path), "name": path.name, "content": path.read_text(encoding="utf-8", errors="ignore")})
    return out
