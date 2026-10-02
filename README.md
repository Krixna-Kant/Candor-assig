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

`--lexical plain` is BM25 alone. The default, `stem`, stems tokens, applies a small synonym table, resolves people, and follows a short claim chain. `--chain-width` defaults to 3.

If `data/` is not in the checkout, set `CANDOR_DATA` to the directory that contains `native/` and `connectors/`. See `.env.example`.

## What the ranker does

Every citable id is loaded with the harness delivery rules. Retrieval sees only units that exist at `as_of`: delivery time at or before that moment, deletions already applied, edit text already replaced. The ranker is Okapi BM25 over that set, then a short chain. The list is relevance order, at most 20 ids, with at most 3 units from one parent. Answers are a 40-word extract of the top hit so the output file is valid. They are not an answer score.

People are resolved from Slack profiles, named speakers, and email headers. Sarah Kim and Sarah Patel stay distinct. A bare first name that belongs to more than one person selects neither. Segments with no speaker name stay unidentified.

A question about the current state of a fact prefers a later record whose body names a date. A meeting hit can pull Slack from the same few days, and that Slack message can pull the rest of its short channel burst. An email hit pulls the rest of its thread at the same rank. Long sessions are scored on their best window and still emit one id. Mail that tells a model to ignore its instructions stays in the index and ranks below ordinary evidence.

## Train retrieval

Scored with `eval_harness/score_retrieval.py` on `evals/memory_train.jsonl`. No forbidden id was retrieved. `outputs/memory_train.jsonl` is the chain-width 3 row.

| Ranker | Pass rate | Exact passage @5 / @10 / @20 | MRR | Found nothing in top 20 |
|---|---|---|---|---|
| BM25 | 60.0% (95% CI 45%–86%) | 56% / 60% / 68% | 0.5313 | 28% |
| BM25 + stemming and synonyms | 68.0% (95% CI 54%–92%) | 56% / 68% / 68% | 0.6067 | 28% |
| Stemming, entities, chain width 3 | 100% (95% CI 100%–100%) | 72% / 100% / 100% | 0.6627 | 0% |

Chain width is how many extra records one seed may add. The same pass rate, by category, at widths 1, 2, 3, and 5:

| Category | 1 | 2 | 3 | 5 |
|---|---|---|---|---|
| Every category except temporal | 100% | 100% | 100% | 100% |
| temporal | 100% | 100% | 100% | 50% |
| Overall | 100% | 100% | 100% | 96% |

Width 5 misses `MEM-TR-12`: the extra neighbors push one of the two required groups out of the top 10. Widths 1, 2, and 3 pass every train question, with nothing forbidden. Width 3 is the default because it is the widest budget that does not lose a category. It is the current state, the change, and the origin.

The eight misses from the stemming-only ranker are cleared at width 3. `MEM-TR-26` finds the Acme acknowledgment on the proposal's thread. The planted digest stays retrievable and is not in that top 10.

## Limits

- Answers are extracts. Do not read the train file as an answer result.
- The synonym table is small and hand-listed. `ship` is grouped with `launch`, which can pull freight wording into a launch question.
- A shared first name with no last name does not choose either person.
- Width 5 is worse than width 3 on the temporal category. Wider chains are not automatically better.

## Data

`data/` is the mock package shipped with the task. If a host rejects the push because a scanner flags a string inside that package, leave `data/` out of the repository and point `CANDOR_DATA` at a local copy. Do not rewrite the package to get past the scanner.
