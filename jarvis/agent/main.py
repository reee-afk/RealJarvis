#!/usr/bin/env python3
"""JARVIS server. Stdlib only: http.server + json. No frameworks."""
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.env import load_env

load_env()

from agent import data, memory, router, vault, voice  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
UI_DIR = BASE_DIR / "ui"
PORT = int(os.environ.get("JARVIS_PORT", "8420"))
HOST = os.environ.get("JARVIS_HOST", "127.0.0.1")  # loopback only — never exposed, no firewall prompt


class Handler(BaseHTTPRequestHandler):
    server_version = "JARVIS/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------------------------------------------------------------- helpers
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _serve_static(self, rel_path: str) -> None:
        rel_path = rel_path.lstrip("/") or "index.html"
        path = (UI_DIR / rel_path).resolve()
        if UI_DIR not in path.parents and path != UI_DIR:
            self._send_json({"error": "not found"}, 404)
            return
        if not path.exists() or not path.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self._send_bytes(path.read_bytes(), content_type)

    # -------------------------------------------------------------------- GET
    def do_GET(self):
        if self.path == "/" or self.path == "":
            self._serve_static("index.html")
        elif self.path == "/api/graph":
            idx = vault.get_index()
            nodes = [{k: v for k, v in n.items() if k != "content"} for n in idx["nodes"]]
            self._send_json({"nodes": nodes, "edges": idx["edges"]})
        elif self.path == "/api/status":
            self._send_json(
                {
                    "demo": data.is_demo(),
                    "llm_configured": router.is_llm_configured(),
                    "voice_configured": voice.is_configured(),
                    "node_count": vault.node_count(),
                    "counts_by_type": vault.counts_by_type(),
                }
            )
        elif self.path.startswith("/api/node"):
            from urllib.parse import urlparse, parse_qs

            qs = parse_qs(urlparse(self.path).query)
            node_id = qs.get("id", [None])[0]
            node = vault.get_node(node_id) if node_id else None
            if node:
                self._send_json(node)
            else:
                self._send_json({"error": "not found"}, 404)
        elif self.path.startswith("/api/path"):
            from urllib.parse import urlparse, parse_qs

            qs = parse_qs(urlparse(self.path).query)
            a, b = qs.get("a", [None])[0], qs.get("b", [None])[0]
            path = vault.shortest_path(a, b) if a and b else []
            self._send_json({"path": path})
        elif self.path.startswith("/api/memory"):
            self._send_json({"memories": memory.all_memories()})
        else:
            self._serve_static(self.path)

    # ------------------------------------------------------------------- POST
    def do_POST(self):
        if self.path == "/api/chat":
            body = self._read_json()
            message = (body.get("message") or "").strip()
            if not message:
                self._send_json({"error": "empty message"}, 400)
                return
            result = router.handle_message(message)
            self._send_json(result)
        elif self.path == "/api/speak":
            body = self._read_json()
            text = (body.get("text") or "").strip()
            if not text:
                self._send_json({"error": "empty text"}, 400)
                return
            if not voice.is_configured():
                self._send_json({"error": "ELEVENLABS_API_KEY not configured"}, 503)
                return
            try:
                audio = voice.text_to_speech(text)
                self._send_bytes(audio, "audio/mpeg")
            except voice.VoiceError as exc:
                self._send_json({"error": str(exc)}, 502)
        elif self.path == "/api/listen":
            if not voice.is_configured():
                self._send_json({"error": "ELEVENLABS_API_KEY not configured"}, 503)
                return
            content_type = self.headers.get("Content-Type", "audio/webm")
            audio_bytes = self._read_body()
            if not audio_bytes:
                self._send_json({"error": "empty audio"}, 400)
                return
            try:
                text = voice.speech_to_text(audio_bytes, content_type)
                self._send_json({"text": text})
            except voice.VoiceError as exc:
                self._send_json({"error": str(exc)}, 502)
        elif self.path == "/api/reset":
            router.reset_history()
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "not found"}, 404)


def main():
    idx = vault.get_index()
    print(f"JARVIS — indexed {len(idx['nodes'])} files, {len(idx['edges'])} links "
          f"({'DEMO' if data.is_demo() else 'REAL'} data)")
    for t, c in sorted(vault.counts_by_type().items(), key=lambda kv: -kv[1]):
        print(f"  {t}: {c}")
    print("  top hubs:", ", ".join(n["title"] for n in vault.top_hubs(10)))
    print(f"  model: {'connected' if router.is_llm_configured() else 'NOT CONFIGURED — heuristic routing'}")
    print(f"  voice: {'connected' if voice.is_configured() else 'NOT CONFIGURED'}")
    print(f"\nServing on http://{HOST}:{PORT}\n")

    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        # Already running (a prior instance, or the always-on task) — this is
        # not a failure worth restarting over, so exit clean rather than let
        # a service manager's restart-on-failure loop spin forever.
        print(f"Port {PORT} is already in use — JARVIS is probably already running. ({exc})")
        sys.exit(0)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
