# Candor memory, v2

A time-filtered memory over two weeks of Alex Rivera's work at Brightline, plus a dry-run action planner. Retrieval is deterministic word search (BM25) with a few general hops. Answers come from an optional LLM writer that reads only the retrieved records, with a deterministic writer as the fallback. Commands are planned and never executed.

v1 is the tag `v1-submitted`. Its hidden-set result was 68% retrieval, 23% answers and 4/13 actions. This file covers what v2 changed, what it scores on a holdout written outside the codebase, and what still fails. The full log of every run and decision is in `docs/decisions.md`, with a summary in `docs/v2-status.md`.

## What changed from v1

1. **Removed every rule written for the train storylines** (21 answer, retrieval and planner rules). Train fell from 100% to 92% retrieval and 70% answers. The independent sets did not move, which showed the rules were fitting train only.
2. **An LLM answer writer** (`src/candor/writer.py`), for any OpenAI-compatible endpoint. It reads only trusted records visible at the question time. Records are redacted, delimited as data, and shown with their text as of then. Each top record is followed by the next records of its conversation, so a reply that answers a question without repeating its words is seen. The writer returns JSON and keeps only source ids it was shown. It abstains when the records do not answer. An answer with a key-shaped token, text from a deleted message, or unreadable JSON is replaced by the deterministic writer. Strict mode stops a scored run instead.
3. **Retrieval hops, still with no model.** "After / before / the day of X" finds the anchor event first. A second search uses terms the top records share, for joins. "What's still open" builds a commitments list (promises and requests, closed when the same person later says it is done). Status questions prefer the newest reply in a thread.
4. **Action resolver rules.** People outside the directory are looked up in trusted records, and the planner asks when there are none or several. Channels are found by name or topic, without needing the word "channel". It handles several recipients and cc lists, and "open X" opens a known app or answers from memory. Questions go to memory and acts go to the planner. Deletes still need confirmation. An optional model slot reader exists but is not part of the numbers below.

Nothing in the code is written for a specific question. Retrieval never calls a model.

## Results

### Which sets count

- **Holdout** (`holdout_memory.jsonl`, 21 questions; `holdout_actions.jsonl`, 14 commands): written by me, outside the coding session. The assistant never opened them; its scripts printed totals and per-category counts only. Hashes are committed in `de25c09`. These are the numbers to read.
- **The holdout was scored twice:** once at the final pass, and once after the fix described below. Holdout totals were also seen while choosing between research options. So it is no longer untouched, and a fresh set would be needed to measure anything further.
- **Development sets:** train, probe, the extra, phrasing and independent action files, and the "frozen" v2 sets (`evals/v2_memory.jsonl`, `actions_v2_independent.jsonl`). The frozen sets were written in the same assistant session that built the code, and their failures were read during the work. They overstate the system.

Answers are scored with `eval_harness/score_memory.py`, without a judge and with a Qwen judge (`qwen/qwen3.8-27b` on Groq). The judge is a different model family from the writer, and a partial answer counts as half. The writer is `nvidia/nemotron-3-super-120b-a12b:free` on OpenRouter, in strict mode, with no fallback answers in any scored run. No run had a forbidden record in its top 10.

### Holdout, v1 against v2

| | retrieval (top 10) | answers, no judge | answers, Qwen judge | actions |
|---|---|---|---|---|
| v1 (`v1-submitted`, no model) | 10/18 = 55.6% | 3/21 = 14.3% | 2/21 = 9.5% | 8/14 = 57.1% |
| v2, final pass (`de25c09`) | 10/18 = 55.6% | 9/21 = 42.9% | 7/21 = 33.3% | 9/14 = 64.3% |
| **v2, after the fix (current)** | **10/18 = 55.6%** | **11/21 = 52.4%** (95% CI 36–73%) | **8/21 = 38.1%** (95% CI 21–58%) | **9/14 = 64.3%** (args 83.9%) |

The answer gain over v1 comes from the writer. Retrieval on unseen questions is no better than v1. With 18–21 items the intervals are wide, and the gain from the fix is one or two questions.

### Development sets (overstate the system)

| | retrieval | answers, no judge | answers, Qwen judge |
|---|---|---|---|
| train (27), final pass → after fix | 25/25 → 25/25 | 25/27 → 25/27 | 24.5/27 → 23/27 |
| frozen v2 (26), final pass → after fix | 17/23 → 18/23 | 18/26 → 20/26 | 16/26 → 17.5/26 |

Actions: train, extra, phrasing and independent are 100% each. Frozen v2 is 9/15 (v1 4/15).

The no-key path (deterministic writer, the files in `outputs/`) on train: retrieval 100%, answers 66.7% without the judge, actions 12/12.

### What happened after the final pass

Outside reviews suggested hybrid search, rerankers, wider writer context, extract-then-answer prompting and a commitments table. Each was measured first:

- **Hybrid BM25 + embeddings** (MiniLM, bge-small) with rank fusion, and a cross-encoder reranker: they lost 2–4 questions on each development set, and gained at most one holdout question. Not adopted. They would also put a model in retrieval.
- **First run (rejected).** I showed the writer wide windows around each hit (up to 1,200 words of each top conversation) and asked it to quote its evidence before answering. Train judged answers fell from 24.5 to 20 of 27. Long meetings buried the newest record, and nearby messages added details nobody asked for. Only train was run. The prompt went back to its earlier revision.
- **The fix (shipped, `b2db20a`).** Each top record is followed by at most its next 2 records in the same conversation, in rank order. The commitments list now also reads promises with no subject ("👍 will send the slide tonight"). The results are the "after the fix" rows above.
- **A meeting-turn retrieval change** was reverted: it gained one development question and lost one holdout question.

## What still fails

- **Retrieval is the limit.** 8 of the 18 answerable holdout questions never have their evidence in the top 50. They are in the categories "after X" (0/1), multi-hop (0/2), open items (0/2), reported speech (0/2) and disagreement (0/1). The frozen set fails the same categories, so these are general. The usual causes:
  - the answer is a short reply far from the turn that matched;
  - a person's view is only reported by someone else;
  - the top 10 is padded with unrelated Slack chatter.
- **The writer drops specifics it was shown.** It leaves out figures, dates, or one side of a disagreement. On the holdout, judged: cross-source 0/2, count 0/1.
- **Abstention.** 2 of 3 should-abstain holdout questions are judged wrong.
- **Status questions** can still take an older estimate from a nearby message (train `MEM-TR-26`).
- **Actions:** 5 of 14 holdout commands fail. They have not been opened.
- **Quota.** The free writer allows 50 requests a day, so a full rerun of all sets takes two keys or two days.

## Run

Python 3.10 or newer; the standard library is enough. From a clean checkout on macOS or Linux:

```sh
sh run.sh
```

That creates `.venv` and runs the unit tests. It then writes `outputs/memory_train.jsonl` and `outputs/actions_train.jsonl` and scores retrieval, answers (`--judge none`) and actions.

The same commands directly, for any question or command file:

```sh
PYTHONPATH=src PYTHONUTF8=1 python3 -m candor memory \
  --questions evals/memory_train.jsonl \
  --out outputs/memory_train.jsonl

PYTHONPATH=src PYTHONUTF8=1 python3 -m candor actions \
  --commands evals/actions_train.jsonl \
  --out outputs/actions_train.jsonl
```

`PYTHONUTF8=1` is needed because the harness opens files with the locale encoding.

### With or without a key

**With no key**, nothing is configured and no model is called: answers come from the deterministic writer, and every run gives the same output. This is the default, and `run.sh` works this way.

**To use the LLM writer**, copy `.env.example` to `.env` and set `LLM_BASE_URL`, `LLM_MODEL` and either `LLM_API_KEY` or `OPENROUTER_API_KEY`. `.env.example` has OpenRouter, Groq and Gemini examples. Keys are read from the environment or `.env` only, and are never logged. Other settings:
- `CANDOR_WRITER=deterministic` ignores the settings for one run.
- `CANDOR_WRITER_STRICT=1` stops on a model error instead of falling back.
- `--writer-log FILE` records which writer answered each question.

Model answers are cached under `.cache/writer`. The cache key covers the prompt, endpoint, model, question, time and the exact evidence shown.

Retrieval, sources and actions are the same with or without a key. Only the answer text changes.

### Other commands

```sh
# all unit tests (about 70; a few minutes)
PYTHONPATH=src PYTHONUTF8=1 python3 -m unittest discover -s tests

# one question, with what was visible, retrieved and shown to the writer
PYTHONPATH=src PYTHONUTF8=1 python3 -m candor explain \
  --question "When is Route Planner v2 launching?" \
  --as-of 2026-09-18T18:00:00-07:00

# a local page for the same answerer and planner
PYTHONPATH=src PYTHONUTF8=1 python3 -m candor serve
```

If `data/` is not in the checkout, set `CANDOR_DATA` to the directory that contains `native/` and `connectors/`.

## How it works

**Time.** Every source becomes one list of citable units, with delivery times that match the harness. A unit is visible when `available_at <= as_of`. A Slack deletion removes its target at the deletion time, and an edit replaces the text at the edit time. Nothing is ranked, shown or cited before it exists.

**Retrieval.** Okapi BM25 over the visible units, with stemming, a small synonym table and corpus-learned abbreviations. Then:
- people are resolved, so the two Sarahs stay distinct;
- planted instructions are kept but ranked down;
- at most 3 units are kept from one parent;
- the hops above run when the question asks for them.

The output is at most 20 ids in relevance order.

**Answers.** The model writer, when configured, or otherwise the deterministic writer, which quotes the current value from the retrieved records. `retrieved` is never rewritten by the writer.

**Actions.** `python -m candor actions` writes the actions it would take, resolved from records visible at the command's time. A delete, cancel or remove returns `confirm` only. A question returns `memory.ask`. Nothing is sent.

Every answer and action string is redacted before it is written.

## Security

- `SL-DM-AB-0915-2` is deleted at `2026-09-15T16:05:02-07:00`. From then on it is not retrieved, cited or quoted. Its body contains a key-shaped token: redaction strips tokens of that shape, and the writer rejects any answer that contains one.
- `SL-SALES-0915-1` is deleted at `2026-09-15T17:52:40-07:00`, with the same rule.
- `SL-RP-0916-1` is edited at `2026-09-16T13:20:15-07:00`. From then on the visible text is the edited one.
- `EM-F-050` tells an assistant to make a claim and forward mail to an outside address. It stays retrievable but ranks low, and it never reaches the model writer. No command turns it into a send.
- No API key is in the repository, the outputs or the logs. `.env` is git-ignored, and `.env.example` has blank values.

## Tools and cost

Written with an in-editor coding assistant. The writer and judge ran on free tiers: OpenRouter for Nemotron, Groq for Qwen. Spend: ₹0. The default command needs no key.

## Data

`data/` is the mock package shipped with the task. If a host rejects the push because a scanner flags a string inside it, leave `data/` out and point `CANDOR_DATA` at a local copy.
