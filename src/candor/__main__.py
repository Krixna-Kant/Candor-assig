"""Command line. `python -m candor memory` writes one JSON object per question."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from candor.actions import plan
from candor.explain import explain_text
from candor.ingest import load_corpus
from candor.redact import has_key_shape, redact
from candor.report import write_failure_report
from candor.retrieve import retrieve
from candor.serve import serve
from candor import writer
from candor.writer import respond


def _load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _memory(args: argparse.Namespace) -> None:
    corpus = load_corpus(args.data)
    questions = _load_jsonl(Path(args.questions))
    stem = args.lexical == "stem"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    origins: Counter[str] = Counter()
    log_rows = []
    config = writer.settings()
    model = config.model if config else "deterministic"
    with out_path.open("w", encoding="utf-8") as handle:
        for item in questions:
            as_of = datetime.fromisoformat(item["as_of"])
            ranked = retrieve(
                corpus, item["question"], as_of,
                stem=stem, chain_width=args.chain_width, parent_cap=args.parent_cap,
            )
            before = dict(writer.STATS)
            answer, sources, abstained, origin = respond(corpus, item["question"], as_of, ranked)
            origins[origin.split(":", 1)[0]] += 1
            spent = {name: writer.STATS[name] - before[name] for name in before if writer.STATS[name] != before[name]}
            log_rows.append({"id": item["id"], "writer": origin, "model": model, **spent})
            answer = redact(answer)
            if has_key_shape(answer):
                raise SystemExit(f"{item['id']}: refused to write a key-shaped answer")
            row = {
                "id": item["id"],
                "answer": answer,
                "sources": sources,
                "retrieved": [record.id for record in ranked],
                "abstained": abstained,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    if args.writer_log:
        log_path = Path(args.writer_log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("".join(json.dumps(row) + "\n" for row in log_rows), encoding="utf-8")
    summary = ", ".join(f"{name} {count}" for name, count in sorted(origins.items()))
    print(f"wrote {len(questions)} answers to {out_path} (lexical={args.lexical}; writer {model}: {summary})")
    print("writer requests: " + ", ".join(f"{name} {count}" for name, count in writer.STATS.items()))
    fallbacks = [row["id"] for row in log_rows if row["writer"].startswith("fallback")]
    if fallbacks:
        print(f"fell back to the deterministic writer for: {', '.join(fallbacks)}")


def _actions(args: argparse.Namespace) -> None:
    corpus = load_corpus(args.data)
    commands = _load_jsonl(Path(args.commands))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for item in commands:
            actions = plan(corpus, item["command"], datetime.fromisoformat(item["as_of"]))
            blob = json.dumps(actions)
            if has_key_shape(blob):
                raise SystemExit(f"{item['id']}: refused to write a key-shaped action")
            handle.write(json.dumps({"id": item["id"], "actions": actions}, ensure_ascii=False) + "\n")
    print(f"wrote {len(commands)} action plans to {out_path}")


def _explain(args: argparse.Namespace) -> None:
    corpus = load_corpus(args.data)
    text = explain_text(corpus, args.question, datetime.fromisoformat(args.as_of))
    if has_key_shape(text):
        raise SystemExit("refused to print a key-shaped value")
    print(text, end="")


def _serve(args: argparse.Namespace) -> None:
    serve(port=args.port, data=args.data)


def _report(args: argparse.Namespace) -> None:
    corpus = load_corpus(args.data)
    text = write_failure_report(corpus, Path(args.gold), Path(args.answers), Path(args.out))
    print(text, end="")


def main() -> None:
    parser = argparse.ArgumentParser(prog="candor")
    parser.add_argument("--data", default=None, help="data directory, or set CANDOR_DATA")
    sub = parser.add_subparsers(dest="command", required=True)

    memory = sub.add_parser("memory", help="answer a JSONL file of questions")
    memory.add_argument("--questions", required=True)
    memory.add_argument("--out", required=True)
    memory.add_argument("--lexical", choices=("plain", "stem"), default="stem")
    memory.add_argument("--chain-width", type=int, default=3)
    memory.add_argument("--parent-cap", type=int, default=3)
    memory.add_argument("--writer-log", default=None, help="write which writer answered each question")
    memory.set_defaults(func=_memory)

    actions = sub.add_parser("actions", help="plan a JSONL file of commands without executing them")
    actions.add_argument("--commands", required=True)
    actions.add_argument("--out", required=True)
    actions.set_defaults(func=_actions)

    explain = sub.add_parser("explain", help="show why one answer was written")
    explain.add_argument("--question", required=True)
    explain.add_argument("--as-of", required=True)
    explain.set_defaults(func=_explain)

    page = sub.add_parser("serve", help="open a local page for questions and dry-run commands")
    page.add_argument("--port", type=int, default=8765)
    page.set_defaults(func=_serve)

    report = sub.add_parser("report", help="per-question retrieval failures against a gold file")
    report.add_argument("--gold", required=True)
    report.add_argument("--answers", required=True)
    report.add_argument("--out", required=True)
    report.set_defaults(func=_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
