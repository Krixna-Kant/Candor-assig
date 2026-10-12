# Retrieval decisions

The train set was used for development. `evals/memory_probe.jsonl` is 15 paraphrases of it. After the first probe score, that file is a dev set: class-level fixes may be checked against it. It is not a held-out set. There is no separate 24-question file in this repo.

## What the probe printout showed

On the full ranker before the fixes below, 5 of 14 coverage questions passed at top 10. Exact passage at 20 was 79%.

The top 10 for the misses was not one meeting filling the list. Two patterns showed up.

Records already found, then cut off. `MEM-PR-02` at 12, `MEM-PR-05` at 13, `MEM-PR-21` at 13, `MEM-PR-26` at 18, and one group of `MEM-PR-10` at 12. A parent cap of 2 was measured. The train pass rate fell to 96% because `MEM-TR-04` failed, and the probe rose only to 6/14. The cap stayed at 3.

Records absent from the top 20. `MEM-PR-13` ("preparation" against "prep") at 46. `MEM-PR-18` ("single sign-on" against SSO) at 57. `MEM-PR-25` found the flight and never the calendar day, because the hop ran only when the question said "calendar". `MEM-PR-20` had the email at rank 1 and the dictation at 20, because the source cue listened only for "dictate".

## Rules added

Query expansion, not document expansion.

- If a question contains a run of words whose initials match an all-caps token attested in the corpus, the query gains that token. Ordinary words and SQL keywords are not treated as acronyms. The pair is not stored as a special case.
- If a question word of 8 or more letters has a corpus token of 4 to 6 letters as a prefix, the query gains that shorter token. That is how "preparation" meets "prep". It is not an acronym.

A question about the day of another event ("day of", "the day I") uses the same calendar lookup as a question that says "calendar": take a date from a travel record already in the hits, then add calendar events on that date.

A spoken note ("voice memo", "voice note", "audio note", "dictate") boosts dictation the same way. The boost is uniform, so it cannot reorder two dictations from the same day by itself. Inserting the dictations from a named day is what moves them.

Embeddings stay off the default command.

## After those rules

Train: 27/27 still pass. Nothing forbidden. Exact passage at 5 moved from 72% to 68%. One train question left the top 5 and stayed inside the top 10. MRR 0.6467.

Probe: 9/14 coverage questions pass (was 5/14). Exact passage at 20 is 100% (was 79%). Nothing forbidden. Still outside the top 10: `MEM-PR-02` at 12, `MEM-PR-05` at 14, `MEM-PR-21` at 13, `MEM-PR-26` at 18, and `MEM-PR-10` with one of three groups at 12.

# v2

## Frozen sets

`evals/v2_memory.jsonl` (26 questions) and `actions_v2_independent.jsonl` (15 commands) were written before any v2 code change. They were written with an AI assistant from the raw files in `data/`. No system output was looked at while writing them. They cover topics the train set does not ask about, plus the question types the hidden-set feedback pointed to: "after X" questions, joins, "what's still open", questions that should not be answered, people outside the directory, channels named without the word "channel", meetings with several people, and "open X" when X is not an app.

Every id in `needed`, `evidence` and `also_supports` was checked with `eval_harness/records.py`. Each one exists, can be seen at the question's `as_of`, and has not been deleted by then. Every email address and channel in the action file appears in the data. Gary Holm has no address anywhere in the data, so the expected action for him is clarify.

These sets are not truly held out. The same assistant that will change the code also wrote them. They are frozen so that this cannot change after the fact. They are not edited after this commit.

| file | sha256 |
|---|---|
| `evals/v2_memory.jsonl` | `983c9a4e7bcfedd2af19d1cbc034a2862775bb1ddcd6847aa9beccf657a9c835` |
| `actions_v2_independent.jsonl` | `8912dac9580aaaffd0be4763b0fc9e54d96f864cef8914e7042be868d78ee2cc` |

The hashes are of the files with LF line endings, which is how git stores them. A Windows checkout may convert them to CRLF, so check with `git show HEAD:evals/v2_memory.jsonl | sha256sum`.

## v1 baseline (tag `v1-submitted`, no code changes)

| set | retrieval | answers strict (judge none) | actions |
|---|---|---|---|
| train | 27/27 (100%) | 100% | 12/12 |
| v2 memory (frozen) | 73.9% | 23.1% (6/26) | |
| v2 actions (frozen) | | | 4/15 (26.7%), argument accuracy 59.3% |

For comparison, the hidden-set scores from the review were 68% retrieval, 23% answers and 4/13 actions.

Retrieval misses: `MEM-V2-01`, `06`, `13`, `21` (one of two groups), `23`, `25`. Two of the three questions that should not be answered got an answer instead (`07`, `09`). Action passes: `ACT-V2-01`, `03`, `12`, `15`.

## Step 1: removing rules that follow train storylines

Each rule was removed one at a time, and the removals add up from one row to the next. After each removal, train and the frozen sets were scored again. A rule could stay only if it is general (driven by the question type or the shape of the data) and it raised a frozen-set score. No rule raised a frozen-set score. So every rule was removed, including the general ones.

Train answers are scored with `--judge none`, which checks key terms. A removal can make an answer worse without changing that score. Steps 1–3 are examples: they made five train answers shorter or worse (`MEM-TR-08` now stops at Dana's old "John is fine cutting dark mode" claim), and train still scored 100%.

| # | removed | kind | train retrieval / answers / actions | v2 retrieval / answers / actions | newly failing on train |
|---|---|---|---|---|---|
| 0 | nothing (v1) | | 100 / 100 / 100 | 73.9 / 23.1 / 26.7 | |
| 1 | "Did/Was Name agree": quote that person, another speaker naming them, and a dark-mode "fast-follow/v2.1" line | storyline | 100 / 100 / 100 | same | |
| 2 | send/promise supplements: add sentences with "Friday", "until" + weekday, "works/agreed" | storyline | 100 / 100 / 100 | same | |
| 3 | "and is it done/sent/did it land": add posted/Figma/Notion sentences; append "It was sent." | storyline | 100 / 100 / 100 | same | |
| 4 | calendar-day answer anchored on a flight email, cut at "Flight 2" | storyline | 100 / 96.3 / 100 | same | TR-25 |
| 5 | sentence bonuses for sent/went, signed/reviewing; "until/works" as status words | storyline | 100 / 88.9 / 100 | same | TR-04, TR-26 |
| 6 | +12 for "go with/switch to" when the question says pick/chose/database | storyline | 100 / 85.2 / 100 | same | TR-14 |
| 7 | quote the previous sentence for "Did Name agree/say" and "going to"; also the "Was:" cut on calendar-update mail | storyline / data format | 100 / 85.2 / 100 | same | |
| 8 | drop "second"/"first" from the words that let a second speaker be quoted | storyline | 100 / 85.2 / 100 | same | |
| 9 | answer: current-value block (latest dated sentence, wider band for "right now", cut at "Was:") | question type | 100 / 74.1 / 100 | same | TR-01, TR-02, TR-13 unverified |
| 10 | (repeat of 9; the step-7 edit had already removed the second "Was:" cut) | | 100 / 74.1 / 100 | same | |
| 11 | time question: swap to a sentence that has a time | question type | 100 / 74.1 / 100 | same | |
| 12 | status answer without a date: prefix "On Month day," | question type | 100 / 74.1 / 100 | same | |
| 13 | spoken correction: strip a trailing "… is the median/mean/average" | storyline | 100 / 70.4 / 100 | same | TR-11 unverified |
| 14 | "liabilit" as a mark of a specific second view | storyline | 100 / 70.4 / 100 | same | |
| 15 | "how many days after X did Y": X from meetings/calendar, Y from a sent email | storyline | 100 / 66.7 / 100 | same | TR-12 |
| 16 | "Sep 18" rewritten as "September 18" | formatting | 100 / 66.7 / 100 | same | |
| 17 | retrieval: for "when is / has / do I still", favour later records and records with a written date | question type | 100 / 70.4 / 100 | same | (TR-12 passes again) |
| 18 | retrieval: add the latest records with the rarest question term | question type | 96.0 / 70.4 / 100 | same | TR-26 retrieval |
| 19 | retrieval: calendar day anchored on a flight/United/depart record | storyline | 92.0 / 70.4 / 100 | same | TR-25 retrieval |
| 20 | planner: append "The current NRR is N" for an all-caps term in the command | storyline | 92.0 / 70.4 / 91.7 | same | ACT-TR-10 |
| 21 | planner: "weekly"/"digest" as words that are not first names | data | 92.0 / 70.4 / 91.7 | same | |

The frozen sets did not move at any step. Their failures come from retrieval misses, from answers that quote the wrong sentence, and from planner gaps. None of the removed rules dealt with those. Three tests checked removed behaviour and were deleted: the second-fact quote, the timed-sentence swap with "John on board", and the NRR figure fill. The pay-question abstention check was kept.

### What a frozen score that did not move does and does not show

No change on the frozen set does not prove a rule was useless. The deterministic writer quotes one sentence and does not combine facts, so a general idea such as "prefer the latest value" had no way to show a gain. Two follow-ups are owed:

- "Current value first" comes back as an instruction in the LLM writer's prompt (step 2). It is measured again there on train and on the frozen set.
- Train answers are also scored with a judge (`score_memory.py --judge openai`). The judge uses a different provider from the writer, so the writer is not grading itself. The README reports both the no-judge and the judge numbers.

The two retrieval removals were keyed to particular words, not to an anchor in general. Step 19 looked for a date only in records containing "flight", "united" or "depart", and only when the question said "fly", "flight" or "travel". The answer-side twin (step 4) also cut the sentence at "Flight 2" and quoted the flight only when the question said "fly", "flight" or "denver". The idea behind them is general: find the anchor event, then search around its date. Step 3 rebuilds that from any anchor record, not from flight words.

After step 1: train 92.0% retrieval, 70.4% answers, 11/12 actions. The frozen sets are unchanged from v1. Steps 2–4 have to win back the train losses with general mechanisms: the LLM writer for answers, anchor-first retrieval for "the day of X", and claim chains for "has / still".
