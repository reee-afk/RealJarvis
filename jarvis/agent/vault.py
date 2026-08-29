"""Folders -> searchable graph. Read-only. Never writes anything."""
import re
import zlib
from pathlib import Path

from . import data

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_WORD_RE = re.compile(r"[a-zA-Z0-9']+")

_CACHE = {"nodes": None, "edges": None, "by_id": None, "mtime_key": None}


def _extract_pdf_text(path: Path) -> str:
    """Best-effort, dependency-free PDF text extraction.

    Decompresses FlateDecode streams and pulls text out of Tj/TJ show-text
    operators. Good enough for search; not a real PDF parser. Fails soft.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    text_parts = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.DOTALL):
        chunk = match.group(1)
        try:
            chunk = zlib.decompress(chunk)
        except zlib.error:
            continue
        for tj in re.finditer(rb"\((?:[^()\\]|\\.)*\)\s*Tj", chunk):
            literal = tj.group(0)[:-2].strip()
            text_parts.append(_pdf_unescape(literal))
        for tj_array in re.finditer(rb"\[(.*?)\]\s*TJ", chunk, re.DOTALL):
            for lit in re.finditer(rb"\((?:[^()\\]|\\.)*\)", tj_array.group(1)):
                text_parts.append(_pdf_unescape(lit.group(0)))
    return " ".join(text_parts)


def _pdf_unescape(literal: bytes) -> str:
    if literal.startswith(b"(") and literal.endswith(b")"):
        literal = literal[1:-1]
    try:
        return literal.decode("latin-1", errors="ignore").replace("\\(", "(").replace("\\)", ")")
    except Exception:
        return ""


def _read_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _extract_pdf_text(path)
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _node_type(root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    parts = rel.parts
    if len(parts) > 1:
        return parts[0].lower()
    return {"md": "note", "markdown": "note", "txt": "text", "pdf": "pdf"}.get(
        path.suffix.lower().lstrip("."), "file"
    )


def _title(path: Path, content: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or path.stem
        if line:
            break
    return path.stem


def _build() -> dict:
    nodes = []
    by_stem = {}
    for root, path in data.iter_vault_files():
        content = _read_text(path)
        node_id = str(path)
        node = {
            "id": node_id,
            "path": node_id,
            "title": _title(path, content),
            "type": _node_type(root, path),
            "ext": path.suffix.lower().lstrip("."),
            "content": content,
            "size": len(content),
            "connections": 0,
        }
        nodes.append(node)
        by_stem.setdefault(path.stem.lower(), node_id)

    edges = []
    seen_edges = set()
    for node in nodes:
        if node["ext"] not in ("md", "markdown"):
            continue
        for m in _WIKILINK_RE.finditer(node["content"]):
            target_name = m.group(1).strip().lower()
            target_id = by_stem.get(target_name)
            if not target_id or target_id == node["id"]:
                continue
            key = tuple(sorted((node["id"], target_id)))
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append({"source": node["id"], "target": target_id})

    conn_count = {}
    for e in edges:
        conn_count[e["source"]] = conn_count.get(e["source"], 0) + 1
        conn_count[e["target"]] = conn_count.get(e["target"], 0) + 1
    for node in nodes:
        node["connections"] = conn_count.get(node["id"], 0)

    by_id = {n["id"]: n for n in nodes}
    return {"nodes": nodes, "edges": edges, "by_id": by_id}


def _cache_key() -> tuple:
    key = []
    for root, path in data.iter_vault_files():
        try:
            key.append((str(path), path.stat().st_mtime))
        except OSError:
            pass
    return tuple(sorted(key))


def get_index(force: bool = False) -> dict:
    key = _cache_key()
    if force or _CACHE["mtime_key"] != key:
        built = _build()
        _CACHE.update(built)
        _CACHE["mtime_key"] = key
    return _CACHE


def node_count() -> int:
    return len(get_index()["nodes"])


def counts_by_type() -> dict:
    out = {}
    for n in get_index()["nodes"]:
        out[n["type"]] = out.get(n["type"], 0) + 1
    return out


def top_hubs(limit: int = 10) -> list:
    nodes = sorted(get_index()["nodes"], key=lambda n: n["connections"], reverse=True)
    return nodes[:limit]


def get_node(node_id: str) -> dict | None:
    return get_index()["by_id"].get(node_id)


def search(query: str, limit: int = 5) -> list:
    """Naive keyword scoring: title hits worth more than body hits."""
    terms = [t.lower() for t in _WORD_RE.findall(query) if len(t) > 1]
    if not terms:
        return []
    scored = []
    for node in get_index()["nodes"]:
        title_l = node["title"].lower()
        content_l = node["content"].lower()
        score = 0
        for t in terms:
            score += title_l.count(t) * 5
            score += content_l.count(t)
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    results = []
    for score, node in scored[:limit]:
        snippet = _snippet(node["content"], terms)
        results.append({**{k: v for k, v in node.items() if k != "content"}, "score": score, "snippet": snippet})
    return results


def _snippet(content: str, terms: list, radius: int = 80) -> str:
    lower = content.lower()
    for t in terms:
        idx = lower.find(t)
        if idx != -1:
            start = max(0, idx - radius)
            end = min(len(content), idx + radius)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(content) else ""
            return prefix + content[start:end].strip().replace("\n", " ") + suffix
    return content[:radius].strip().replace("\n", " ")


def shortest_path(source_id: str, target_id: str) -> list:
    idx = get_index()
    adjacency = {}
    for e in idx["edges"]:
        adjacency.setdefault(e["source"], set()).add(e["target"])
        adjacency.setdefault(e["target"], set()).add(e["source"])
    if source_id not in adjacency or target_id not in adjacency:
        return []
    from collections import deque

    queue = deque([[source_id]])
    visited = {source_id}
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == target_id:
            return path
        for neighbor in adjacency.get(node, ()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])
    return []
