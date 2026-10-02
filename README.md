# Candor memory

A time-filtered memory over two weeks of Alex Rivera's work. This commit is the lexical baseline. Later commits add entity resolution, claim chains, answers, and the action commands.

## Run

On macOS, from a clean checkout:

```sh
sh run.sh
```

That creates `.venv`, runs the timeline and `as_of` tests, writes `outputs/memory_train.jsonl`, and scores retrieval with `eval_harness/score_retrieval.py`.

The same command directly:

```sh
PYTHONPATH=src PYTHONUTF8=1 python3 -m candor memory \
  --questions evals/memory_train.jsonl \
  --out outputs/memory_train.jsonl
```

`--lexical plain` is BM25 alone. The default, `stem`, stems tokens and applies a small synonym table (`slip`/`move`/`push`/`delay`, and a few others).

If `data/` is not in the checkout, set `CANDOR_DATA` to the directory that contains `native/` and `connectors/`. See `.env.example`.

## What this commit does

Every citable id is loaded with the harness delivery rules. Retrieval sees only units that exist at `as_of`: delivery time at or before that moment, deletions already applied, edit text already replaced. The ranker is Okapi BM25 over that set. The list is relevance order, at most 20 ids. Answers are a 40-word extract of the top hit so the output file is valid. They are not an answer score.

## Train retrieval

Scored with `eval_harness/score_retrieval.py` on `evals/memory_train.jsonl`. No forbidden id was retrieved.

| Ranker | Pass rate | Exact passage @5 / @10 / @20 | MRR | Found nothing in top 20 |
|---|---|---|---|---|
| BM25 | 60.0% (95% CI 45%–86%) | 56% / 60% / 68% | 0.5313 | 28% |
| BM25 + stemming and synonyms | 68.0% (95% CI 54%–92%) | 56% / 68% / 68% | 0.6067 | 28% |

The second row is what `outputs/memory_train.jsonl` contains. Stemming and synonyms fixed two questions (`MEM-TR-10`, `MEM-TR-12`) and did not clear the misses below.

Failures of the default ranker, top 10. `first@None` means no needed id appears in the top 20 either. Nothing forbidden was in the list.

| Id | Missed group | First needed rank |
|---|---|---|
| MEM-TR-01 | launch-date passages for 18 Sep | none |
| MEM-TR-02 | 10 Sep slip to 14 Oct | none |
| MEM-TR-05 | `EM-0915-ACME-PROP` | none |
| MEM-TR-14 | `CDX-0912` or `MTG-0917-RECRUIT#0014` | none |
| MEM-TR-20 | `DCT-0910-02` (the email side was found) | 1 |
| MEM-TR-21 | geocoding-regression messages | none |
| MEM-TR-25 | board-day calendar and the flight email | none |
| MEM-TR-26 | `EM-0916-ACME-ACK` or `SL-F-0150` | none |

`MEM-TR-01` and `MEM-TR-02` are filled with segments from the 8 Sep planning meeting, which repeats "Route Planner" more often than the later Slack lines. `MEM-TR-14` misses the Codex session: it is one long unit, so length normalization pushes it down. `MEM-TR-26` ranks `EM-F-050` second. That mail is allowed at this `as_of`, and it is the wrong support for whether Acme has signed. Treating it as untrusted is later work.

## Limits

- No entity resolution yet. Two people can share a first name and both still match.
- No claim chain. A question about the current launch date retrieves the earliest planning discussion.
- Answers are extracts. Do not read the train file as an answer result.
- The synonym table is small and hand-listed. `ship` is grouped with `launch`, which can pull freight wording into a launch question.

## Data

`data/` is the mock package shipped with the task. If a host rejects the push because a scanner flags a string inside that package, leave `data/` out of the repository and point `CANDOR_DATA` at a local copy. Do not rewrite the package to get past the scanner.
