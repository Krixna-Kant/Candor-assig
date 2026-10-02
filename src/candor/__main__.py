"""Command line. `python -m candor memory` writes one JSON object per question."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from candor.answer import placeholder
from candor.ingest import load_corpus
from candor.redact import has_key_shape, redact
from candor.report import write_failure_report
from candor.retrieve import retrieve


def _load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _memory(args: argparse.Namespace) -> None:
    corpus = load_corpus(args.data)
    questions = _load_jsonl(Path(args.questions))
    stem = args.lexical == "stem"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for item in questions:
            as_of = datetime.fromisoformat(item["as_of"])
            ranked = retrieve(
                corpus, item["question"], as_of,
                stem=stem, chain_width=args.chain_width, parent_cap=args.parent_cap,
            )
            answer, sources, abstained = placeholder(ranked)
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
    print(f"wrote {len(questions)} answers to {out_path} (lexical={args.lexical})")


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
    memory.set_defaults(func=_memory)

    report = sub.add_parser("report", help="per-question retrieval failures against a gold file")
    report.add_argument("--gold", required=True)
    report.add_argument("--answers", required=True)
    report.add_argument("--out", required=True)
    report.set_defaults(func=_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
