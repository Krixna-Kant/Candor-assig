"""A local page over the same answerer and planner. Nothing is sent."""

from __future__ import annotations

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from candor.actions import plan
from candor.ingest import load_corpus
from candor.models import Corpus
from candor.redact import has_key_shape, redact
from candor.retrieve import retrieve
from candor.writer import respond

_PAGE = (Path(__file__).with_name("page.html")).read_text(encoding="utf-8")
_corpus: Corpus | None = None


def serve(host: str = "127.0.0.1", port: int = 8765, data: str | None = None) -> None:
    global _corpus
    _corpus = load_corpus(data)
    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"open http://{host}:{port}", flush=True)
    server.serve_forever()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] not in ("/", "/index.html"):
            self._send(404, {"error": "not found"})
            return
        body = _PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ("/memory", "/actions"):
            self._send(404, {"error": "not found"})
            return
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            text = str(payload.get("text") or "").strip()
            as_of = datetime.fromisoformat(str(payload["as_of"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._send(400, {"error": "Send text and an as_of timestamp."})
            return
        if not text:
            self._send(400, {"error": "Write a question or a command first."})
            return
        corpus = _corpus
        if corpus is None:
            self._send(500, {"error": "The memory is not loaded."})
            return
        if path == "/memory":
            ranked = retrieve(corpus, text, as_of, stem=True)
            answer, sources, abstained, origin = respond(corpus, text, as_of, ranked)
            answer = redact(answer)
            body = {
                "answer": answer,
                "sources": sources,
                "abstained": abstained,
                "retrieved": [record.id for record in ranked],
                "writer": origin.split(":", 1)[0],
            }
        else:
            actions = plan(corpus, text, as_of)
            body = {"actions": actions}
        if has_key_shape(json.dumps(body)):
            self._send(500, {"error": "Refused to show a key-shaped value."})
            return
        self._send(200, body)

    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
