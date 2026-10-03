# Candor memory

A time-filtered memory over two weeks of Alex Rivera's work at Brightline, plus a dry-run action planner. Retrieval is lexical: BM25, then people and a short chain. Answers are deterministic. Commands are planned and not executed.

Python 3.10 or newer. The standard library is enough. No model is called on the default path.

## Run

On macOS, from a clean checkout:

```sh
sh run.sh
```

That creates `.venv`, runs the timeline, `as_of`, and action tests, writes `outputs/memory_train.jsonl` and `outputs/actions_train.jsonl`, and scores retrieval, answers (`--judge none`), and the dry-run actions.

The same commands directly, including a hidden question file:

```sh
PYTHONPATH=src PYTHONUTF8=1 python3 -m candor memory \
  --questions evals/memory_train.jsonl \
  --out outputs/memory_train.jsonl

PYTHONPATH=src PYTHONUTF8=1 python3 -m candor actions \
  --commands evals/actions_train.jsonl \
  --out outputs/actions_train.jsonl
```

`PYTHONUTF8=1` is set because the harness opens files with the locale encoding, and a non-UTF-8 locale fails on this data. `run.sh` exports it.

`--lexical plain` is BM25 without stemming. The default, `stem`, stems tokens, applies a small synonym table, resolves people, and follows a short claim chain. `--chain-width` defaults to 3. `--parent-cap` defaults to 3.

If `data/` is not in the checkout, set `CANDOR_DATA` to the directory that contains `native/` and `connectors/`. See `.env.example`. The default command does not read an API key.

Unit tests, from the repo root:

```sh
PYTHONPATH=src PYTHONUTF8=1 python3 -m unittest tests.test_timeline tests.test_text tests.test_asof_sweep tests.test_answer tests.test_actions
```

One question, with the records it used:

```sh
PYTHONPATH=src PYTHONUTF8=1 python3 -m candor explain \
  --question "When is Route Planner v2 launching?" \
  --as-of 2026-09-18T18:00:00-07:00
```

A local page for the same answerer and the same dry-run planner. Open the printed address. Listen uses the browser's speech recognition, in Chrome. Ask and Plan work by typing in any browser.

```sh
PYTHONPATH=src PYTHONUTF8=1 python3 -m candor serve
```

The paraphrase file and the phrasing file are separate from `run.sh`. `results/` is created by `run.sh` and is not in git; create it before these commands if you have not run `run.sh`.

```sh
mkdir -p results
PYTHONPATH=src PYTHONUTF8=1 python3 -m candor memory \
  --questions evals/probe_paraphrase.jsonl \
  --out results/probe_paraphrase.jsonl
PYTHONPATH=src PYTHONUTF8=1 python3 eval_harness/score_retrieval.py \
  --gold evals/probe_paraphrase.jsonl --answers results/probe_paraphrase.jsonl \
  --out results/probe_retrieval.json
PYTHONPATH=src PYTHONUTF8=1 python3 eval_harness/score_memory.py \
  --gold evals/probe_paraphrase.jsonl --answers results/probe_paraphrase.jsonl \
  --judge none --out results/probe_memory.json
PYTHONPATH=src PYTHONUTF8=1 python3 -m candor actions \
  --commands evals/actions_phrasing.jsonl --out results/actions_phrasing.jsonl
PYTHONPATH=src PYTHONUTF8=1 python3 eval_harness/score_actions.py \
  --gold evals/actions_phrasing.jsonl --predictions results/actions_phrasing.jsonl \
  --out results/actions_phrasing_score.json
```

## Architecture

Every source becomes one list of citable units. Delivery times match the harness: a meeting segment exists at meeting start plus `end_s`, a calendar event at `updated`, a Codex session at its last event, and everything else at its own timestamp. Codex sessions are one id. Meeting segments and ChatGPT messages keep their real sub-ids. Slack edits and deletions are their own rows.

Two clocks stay separate. Transaction time is when a unit may be seen: `available_at <= as_of`, a deletion removes the target at the deletion timestamp, and an edit replaces the text at the edit timestamp. Valid time is what the text claims (a launch date, a promise). A disagreement is not a supersession. Reported speech stays attributed to the person who reported it.

Retrieval sees only `visible()` units. Okapi BM25 (k1 1.5, b 0.75) scores the harness display text. A long unit is scored on its best 80-token window and still emits one id. The list is relevance order, at most 20 ids. Ties keep input order. Nothing is sorted alphabetically or by date as the ranking method.

After BM25, a wanted person is boosted and the other person who shares a first name is downranked. A bare shared first name selects nobody, so the two Sarahs stay distinct. Unidentified speakers stay unidentified. Mail that tells a model to ignore its instructions stays in the index and is multiplied down unless the question is about that message. A current-state question prefers a later record whose body names a date. One seed may pull a few neighbors: later mentions of a rare query term, Slack in the same channel within a few days, and the rest of an email thread. A question about the day of a trip also pulls that day's calendar events. At most 3 units from one parent survive.

Answers quote the current value from that list, in the text visible at `as_of`, then a second fact when the question asks for one (who else spoke, whether it was sent, what was promised). A question about a promise also quotes the deadline move and the acceptance when those sentences are visible. A superseded number is left out. The answer abstains only when every remaining topic token is absent from the visible corpus. Sources are ids the answer used. `retrieved` is the ranked list and is not rewritten by the answerer.

`python -m candor actions` reads `{"id","command","as_of"}` and writes the actions it would take. It does not send mail, post to Slack, or change a calendar. People, channels, and event times come from records visible at `as_of`. A shared first name is used only when one person owns the topic; otherwise the plan asks which person. A delete, erase, cancel, or remove returns `confirm` and nothing else. A question returns `memory.ask`. A figure such as NRR is copied from the latest visible record that states one.

Every answer and every action string passes through the same redaction before it is written. The writer refuses a key-shaped token.

## Decisions

The default path is deterministic and offline. A hidden question is not in any cache, and a float or a failed download must not change a file the grader re-runs. Embeddings stay off.

Chain width 3 is the default. Widths 1, 2, and 3 all pass every train question. Width 3 is a budget of the current state, the change, and the origin. It is not a measured optimum: exact passage at 5 is higher at widths 1 and 2. Width 5 drops a train question, so wider is not automatically better.

The parent cap stays at 3. A cap of 2 was measured on this tree and dropped a train question.

Query expansion is query-side only. A run of words whose initials match an attested all-caps token adds that token. A long query word adds a shorter corpus token that is a prefix of it, which is how "preparation" meets "prep". Those pairs are learned from the corpus. They are not special cases for the train wording.

Answers lead with the current value. Putting the old value back makes `--judge none` mark the row unverified, and an unverified row counts as wrong. The rubrics ask for the current value. The old value is not added on purpose.

## Eval results

Re-scored on this tree. No forbidden id was retrieved in any of these runs. The 95% interval is what the harness prints. When every row passes, that interval is 100%–100%. It is not an estimate of the hidden set.

### Retrieval

`eval_harness/score_retrieval.py` on `evals/memory_train.jsonl`. A question passes when every required group has a member in the top 10 and no forbidden id is in the top 10. Abstentions are not coverage-scored. `outputs/memory_train.jsonl` is the chain-width 3 file.

| Setting | Pass rate | Exact passage @5 / @10 / @20 | MRR | Nothing in the top 20 |
|---|---|---|---|---|
| BM25, no stemming | 64.0% (95% CI 48%–92%) | 52% / 64% / 68% | 0.528 | 28% |
| Chain width 1 | 100% | 72% / 100% / 100% | 0.637 | 0% |
| Chain width 2 | 100% | 72% / 100% / 100% | 0.648 | 0% |
| Chain width 3, the default | 100% (95% CI 100%–100%) | 68% / 100% / 100% | 0.6467 | 0% |
| Chain width 5 | 96.0% (95% CI 90%–100%) | 68% / 96% / 100% | 0.645 | 0% |
| Parent cap 2, width 3 | 96.0% (95% CI 90%–100%) | 72% / 96% / 96% | 0.6513 | 0% |

Width 5 misses `MEM-TR-12`, one of the two temporal questions. The extra neighbors push one of its two required groups out of the top 10. Parent cap 2 misses `MEM-TR-04`.

### Answers

`eval_harness/score_memory.py --judge none`. This is the offline rule score. The official score adds a judge, which can only confirm or lower a row.

| File | Strict | Unverified | Hard failures | Source recall | Source precision |
|---|---|---|---|---|---|
| `evals/memory_train.jsonl` (27) | 100% (95% CI 100%–100%) | 0 | 0 | 0.8533 | 0.99 |
| `evals/memory_probe.jsonl` (15) | 100% (95% CI 100%–100%) | 0 | 0 | 0.8929 | 0.9643 |

The probe is 15 paraphrases written while the answerer was being built. It is not held out. A promise answer quotes the later deadline and the acceptance as well as the send. On the train question that asks whether the Acme proposal went out, the text includes Friday, "until Tuesday the 15th," and "Tuesday works." A time question quotes a sentence that contains a time. "How much does Ben Carter earn?" abstains, because pay is not in the corpus, and so does "What is Dana's salary?" The no-judge score stayed 27/27 with 0 unverified.

One pass of Groq's `openai/gpt-oss-120b`, temperature 0, on these train answers scored 98.1%. It marked `MEM-TR-24` partial. Two earlier passes on close drafts of the same answers scored 88.9% and 100%. The judge moves between calls, so 98.1% is one sample. It is not on the default path, and the committed train file is the no-key run.

### Probe retrieval

Same scorer, `evals/memory_probe.jsonl`. One line is an abstention (`MEM-PR-16`) and is not coverage-scored. 9 of the other 14 pass.

| | |
|---|---|
| Harness score | 64.3% (95% CI 44%–90%, n=15) |
| Exact passage @5 / @10 / @20 | 50% / 64% / 100% |
| MRR | 0.4581 |
| Nothing in the top 20 | 0% |

Still outside the top 10, all inside the top 20: `MEM-PR-02` first at 12, `MEM-PR-05` at 14, `MEM-PR-10` with one group missing at 10 (first hit at 1), `MEM-PR-21` at 13, `MEM-PR-26` at 18. These are ordering misses. The ranker was not tuned against this file after those ranks were seen.

### Second paraphrase file

`evals/probe_paraphrase.jsonl` is the 24-line `probe.jsonl` copied unchanged. Twenty-two lines point `paraphrase_of` at a train id, and the gold text, rubric, and `needed` ids are the train labels. The questions are different from `evals/memory_probe.jsonl`. This is a wording check, not a held-out set. The ranker was not tuned on it. The answer number below is after the writer change. The first pass, before that change, was 33.3%.

| | |
|---|---|
| Retrieval | 68.2% (95% CI 46%–89%, n=24) |
| Exact passage @5 / @10 / @20 | 50% / 68% / 82% |
| Nothing in the top 20 | 14% |
| MRR | 0.456 |
| Forbidden | 0 |
| Answers, `--judge none` | 41.7% (95% CI 20%–65%), 0 unverified |

Seven coverage questions miss the top 10: `MEM-PR-01`, `MEM-PR-04`, `MEM-PR-05`, `MEM-PR-10`, `MEM-PR-11`, `MEM-PR-13`, `MEM-PR-21`. Ten answers pass, including both abstentions (`MEM-PR-23`, `MEM-PR-24`). The other fourteen miss a key term. Most of those fourteen are the retrieval misses above, or a sentence that overlaps the question and still omits the value.

### Actions

`eval_harness/score_actions.py`. A command passes only when the predicted list matches the expected list or one accepted alternative.

| Set | Pass rate | Argument accuracy |
|---|---|---|
| `evals/actions_train.jsonl` (12) | 12/12 | 100% |
| `evals/actions_extra.jsonl` (33) | 33/33 | 100% |
| `evals/actions_phrasing.jsonl` (10) | 10/10 | 100% |
| `actions_phrasing_independent.jsonl` (10), independent phrasing check, written outside the codebase | first run 3/10 (argument accuracy 53.3%); after the planner fix 10/10 | 100% after the fix |

The extra file was written against this planner. It is a regression set, not a hidden set. One extra command asks for the NRR figure before Ben's correction and expects 118; the same wording after the correction expects 112. Both come from the records visible at `as_of`. The phrasing file uses different verbs and word order, including cancel, "the other Sarah," two intents in one command, "in two days," and "the day after tomorrow." It was scored once.

The independent file sits at the repo root. It was not edited, and the ranker was not tuned to its wording. The first run missed seven commands: a casual "an email" still went to Slack, "push" did not move a calendar event, "set a reminder" was treated as mail, "block" plus a weekday was not a new event, "remind me what…" asked for a time instead of memory, a cc list collapsed into "which person," and a bare first name with no topic was guessed. The planner now treats "push" like move, "block" like book, "an email" as mail, "set a reminder" as a reminder, "remind me what/when/…" with no time as a memory question, a weekday as the next matching day, and cc as its own recipient list. A shared first name still needs a topic. A 1:1 named by a person prefers that person's 1:1 over a group event that only lists them.

## What didn't work

BM25 alone leaves nine train questions out of the top 10: `MEM-TR-01`, `MEM-TR-02`, `MEM-TR-05`, `MEM-TR-12`, `MEM-TR-14`, `MEM-TR-20`, `MEM-TR-21`, `MEM-TR-25`, and `MEM-TR-26`. 28% of scored questions find nothing needed in the top 20. Stemming, people, and the short chain clear those on the train set. The same chain does not clear the five probe questions above.

A parent cap of 2 looked like a way to stop one meeting filling the list. On this tree it drops `MEM-TR-04`, so the cap stayed at 3.

Chain width 5 looked like more context. It drops `MEM-TR-12`.

Adding a superseded date back into the answer makes the no-judge scorer call the row unverified. Unverified counts as wrong. The current value is what gets written.

Fusing `all-MiniLM-L6-v2` (ONNX, via fastembed) with BM25 by reciprocal rank dropped train retrieval from 100% to 88% (exact passage 64% / 88% / 100%, MRR 0.6694) and the no-judge answers to 96.3%. It is not the default. The default path stays the standard library.

The synonym table is small and hand-listed. `ship` is grouped with `launch`, which can pull freight wording into a launch question.

## Security

Findings by id. The secret itself is not written here, and it is not in `outputs/`.

- `SL-DM-AB-0915-2` is a direct message deleted at `2026-09-15T16:05:02-07:00`. From that moment it is not retrieved, cited, or quoted. The body contains a key-shaped token. Redaction strips tokens of that shape on the way out, and the writer refuses to emit one. The ordinary word "password" is not treated as a secret.
- `SL-SALES-0915-1` is deleted at `2026-09-15T17:52:40-07:00`. Same rule: gone at that timestamp.
- `SL-RP-0916-1` is edited by `SL-EV-0916-EDIT1` at `2026-09-16T13:20:15-07:00`. At and after that time the visible text is the edited text.
- `EM-F-050` (thread `TH-PP-0916`, `2026-09-16T10:12:33-07:00`) tells an assistant to make a claim and to forward mail to an address that appears only in that message. The message stays retrievable and ranks below ordinary mail. It is not quoted. No command turns it into a send, including a command that names that address.

## Limits

- The train and dev-probe answer scores under `--judge none` are development scores. A Groq judge can lower a row and cannot raise one, and it is not stable across calls. The 41.7% on `evals/probe_paraphrase.jsonl` is the wording check above, measured after the writer change, and its labels come from the train file.
- The dev probe, the paraphrase file, and the extra action file are not a substitute for the hidden sets.
- A shared first name with no distinguishing topic does not choose a person, in retrieval or in the action planner.
- Calendar history is not in the calendar file. The file is the current snapshot, visible from `updated`. Earlier times show up in mail.
- The action planner is dry-run only. There is no send path.

## Tools and cost

The program was written with an in-editor coding assistant. `python -m candor memory` calls no model and needs no API key. The judge number above used Groq's free tier and is not part of that command. Spend for the submission path: ₹0.

## Questions

- If an answer writer or action planner used an LLM, how would you compare re-run outputs? The default path is deterministic and offline so a re-run matches exactly. Is that the right trade?
- When you run the commit yourselves, is an API key available? The code uses none by default.
- Topic disambiguation: should a hidden command with a shared first name always ask, even when one person owns the topic?

## Data

`data/` is the mock package shipped with the task. If a host rejects the push because a scanner flags a string inside that package, leave `data/` out of the repository and point `CANDOR_DATA` at a local copy. Do not rewrite the package to get past the scanner.
