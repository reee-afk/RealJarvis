"""
Windows always-on entry point. Run with pythonw.exe (no console window).

pythonw.exe leaves sys.stdout/sys.stderr as None, and agent/main.py prints
its startup summary — that combination crashes with
"AttributeError: 'NoneType' object has no attribute 'write'" the moment it
tries. Redirect both to a log file *before* importing anything that prints.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_PATH = BASE_DIR / "jarvis.log"

log_file = open(LOG_PATH, "a", buffering=1, encoding="utf-8")
sys.stdout = log_file
sys.stderr = log_file

sys.path.insert(0, str(BASE_DIR))
from agent.main import main  # noqa: E402

if __name__ == "__main__":
    print("\n--- JARVIS starting ---")
    main()
