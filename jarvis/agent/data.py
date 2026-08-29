"""
THE ONLY FILE THAT TOUCHES REAL DATA.

Every path JARVIS ever reads from disk — demo fixtures or Kunal's real
folders — is resolved here and nowhere else. Read-only, always.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = BASE_DIR / "data" / "demo"
MEMORY_DIR = BASE_DIR / "memory"

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2MB — skip anything bigger
SKIP_DIR_NAMES = {"node_modules", ".git", "__pycache__", ".DS_Store"}


def is_demo() -> bool:
    """Default is demo. Real life is opt-in, never the default."""
    return os.environ.get("JARVIS_DEMO", "1") != "0"


def vault_roots() -> list[Path]:
    if is_demo():
        return [DEMO_DIR] if DEMO_DIR.exists() else []
    raw = os.environ.get("VAULT_PATHS", "")
    roots = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        p = Path(chunk).expanduser()
        if p.exists() and p.is_dir():
            roots.append(p)
    return roots


def memory_dir() -> Path:
    MEMORY_DIR.mkdir(exist_ok=True)
    return MEMORY_DIR


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES or name.startswith(".")


def iter_vault_files():
    """Yield (root, path) for every readable file under every vault root."""
    for root in vault_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                ext = Path(fname).suffix.lower()
                if ext not in (".md", ".markdown", ".txt", ".pdf"):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    if fpath.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                yield root, fpath
