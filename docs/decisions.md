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

**Status after steps 2–4: these are development sets now.** Retrieval was scored and iterated against the memory set, with per-question pass/fail read for step 3. The commands in the action set were known while the planner was built. Their scores below are development scores. A separate holdout, written outside this working session and never opened here, is scored once at the end; that is the closest thing to a hidden-set estimate.

| file | sha256 |
|---|---|
| `evals/v2_memory.jsonl` | `983c9a4e7bcfedd2af19d1cbc034a2862775bb1ddcd6847aa9beccf657a9c835` |
| `actions_v2_independent.jsonl` | `8912dac9580aaaffd0be4763b0fc9e54d96f864cef8914e7042be868d78ee2cc` |

The hashes are of the files with LF line endings, which is how git stores them. A Windows checkout may convert them to CRLF, so check with `git show HEAD:evals/v2_memory.jsonl | sha256sum`.

## Holdout

`holdout_memory.jsonl` (21 questions, 3 of them not answerable) and `holdout_actions.jsonl` (14 commands) were written outside this working session, after retrieval and the planner were final. The assistant that built the code has not opened them. Before this commit they were checked only by scripts that print counts and line numbers, never content:

- every line is valid JSON with the harness's fields;
- no id is reused from another set;
- every cited record exists, is available at the question's `as_of`, and is not deleted by then;
- every email address and channel id in the expected actions appears in `data/`.

They are scored once, in the final pass, with no change to the code afterwards. Only totals and per-category counts are printed. With about 20 and 14 items, the 95% interval is roughly ±20–25 points, so this is a rough estimate of the hidden-set score, not a precise one.

| file | sha256 (LF) |
|---|---|
| `holdout_memory.jsonl` | `a2f378b1f3eccf32d4b4b124dc7a7847bdec345fe1341da2575bc81d2b2a8d55` |
| `holdout_actions.jsonl` | `cc08dd9365c24092f3a65b74be480bd785fd18b5d5079672d32faba7b2e1b86b` |

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

After step 1: train 92.0% retrieval, 70.4% answers, 11/12 actions.

### Judge

The judge is the harness's own `--judge openai` path, pointed at an OpenAI-compatible endpoint. No OpenAI account is used.

- Routine judge: `qwen/qwen3.8-27b` on Groq. The writer in step 2 is `openai/gpt-oss-120b`, so the judge is a different model family.
- Gemini's free tier allows 20 requests a day per model. That is too few for routine runs, so `gemini-2.5-flash` is used only as a spot check on the final numbers.
- The harness is not edited. A scratch wrapper paces its HTTP calls and adds a User-Agent header, which Groq requires. It also asks Groq to hide Qwen's reasoning text. The judge prompt and the parsing are unchanged.

Train answers after step 1, judged by Qwen: **63.0% strict** (70.4% with no judge). The judge downgraded seven answers that pass on key terms:

- `MEM-TR-08` repeats Dana's outdated claim about John.
- `MEM-TR-07`, `MEM-TR-24` and `MEM-TR-20` give the due date or the request but do not say it landed or was sent.
- `MEM-TR-02` also mentions the superseded date.
- `MEM-TR-09` and `MEM-TR-10` each leave out a point the rubric requires.

These are the losses the removed rules were covering up.

### Judged baselines

The judge only runs on answers that already pass the key-term rules, and it can only downgrade them. So the judged score is never higher than the no-judge score. An answer that is correct but misses a key term stays wrong whatever the judge says.

Each judge reply is cached on disk, keyed by provider, model and the full judge prompt. The prompt contains the question, as-of time, reference answer, rubric and answer text. A rerun on the same answers therefore gives the same score, so a change in score means an answer changed.

| answers | train, no judge | train, Qwen judge | frozen v2, no judge | frozen v2, Qwen judge |
|---|---|---|---|---|
| v1 (tag `v1-submitted`) | 100% | 90.7% | 23.1% | 17.3% |
| after step 1 | 70.4% | 63.0% | 23.1% | 17.3% |

Judge noise: I judged the 27 v1 train answers a second time without the cache, and 0 of 27 verdicts changed. An earlier uncached run of the step-1 train answers also gave 63.0%. On this evidence the judge is stable to about one question, but two repeats cannot rule out the odd flip.

The judged numbers measure before against after on the same judge. They do not predict the reviewer's score. Qwen's strictness is not the reviewer's judge, and the hidden set is not this set.

## Step 2: the model answer writer

Writer: `openai/gpt-oss-120b` on Groq, temperature 0. It reads the top 10 trusted retrieved records, with their text as of the question time, key-shaped tokens redacted, and each record in a `<record ...>` block. The prompt says block contents are data, never instructions. The model has no tools. Its source ids are kept only when they name a block it was shown. "Not answerable" becomes "I don't know…" with no sources.

An answer is rejected, and the deterministic writer used instead, if any of these hold:

- it has a key-shaped token;
- it repeats six words in a row from a message deleted by the question time;
- the reply is not valid JSON.

Scored runs set `CANDOR_WRITER_STRICT=1`. A model error then stops the run instead of falling back, so every scored answer below came from the model or its cache. No run had a fallback.

`retrieved` was byte-identical to the deterministic run on every question in every run below.

| run | change | train no judge / judged | frozen no judge / judged |
|---|---|---|---|
| after step 1 | deterministic writer | 70.4 / 63.0 | 23.1 / 17.3 |
| prompt 1 | the writer, prompt as specified | 92.6 / 77.8 | 53.8 / 50.0 |
| + excerpts | long records keep their opening and the 50-word windows that share the most question words, instead of the first 350 words | 96.3 / 81.5 | 61.5 / 57.7 |
| revision 1 | rule 5: when a person's own words appear beside a report of them, give their own words; new rule 7: include the names, dates, numbers and reasons the records give for each part of the question | 92.6 / 83.3 | 65.4 / 63.5 |

Why each change was made. Every change came from a train failure, not from reading frozen answers.

- **Excerpts.** `MEM-TR-14` abstained although retrieval had found the evidence. The record is a 1,977-word Codex session, and the PostGIS passage fell after word 350. This is a fix to how the evidence is built, not to the prompt.
- **Revision 1.** `MEM-TR-08` answered "Yes" from Dana's report that John was fine cutting dark mode. John's own message asking to keep it was in the evidence. `MEM-TR-24`, `MEM-TR-09` and `MEM-TR-10` left out details the rubric needs.
- **The train no-judge drop under revision 1** is `MEM-TR-11`. It now also mentions the 800 figure the speaker corrected away, so the no-judge scorer counts it as unverified. The judge marks it correct.

The prompt names no person, company, channel or product from the data, and `tests/test_writer.py` checks that. The owner's name reaches the model from `ingest.ALEX_NAME`, in each request, not from the prompt template.

One prompt revision is left in the budget of two.

### The "current value first" rule, measured again

Rule 6 is the prompt version of the current-value rule removed in step 1. It was measured on the questions it could affect: 9 train questions (knowledge update, time travel, correction, edited record, commitment status) and 5 frozen ones (time travel, open items). Both runs used step 2 retrieval, strict mode, no fallbacks, and the Qwen judge.

| prompt | train no judge / judged (n=9) | frozen no judge / judged (n=5) |
|---|---|---|
| revision 1, with rule 6 | 88.9 / 94.4 | 60.0 / 60.0 |
| revision 1, without rule 6 | 88.9 / 94.4 | 60.0 / 60.0 |

Rule 6 makes no measurable difference. The same rows fail either way: `MEM-TR-04` is partial (the judge wants the deadline extension) and `MEM-TR-11` is unverified. On the frozen set, the two failures differ only in wording; the questions are the same. Rule 6 stays, because it is part of the prompt every scored run used. Removing it would mean a full re-run for no measured gain. The model follows the current value from the records without being told.

### Groq free-tier limit

`gpt-oss-120b` on the free tier allows 200,000 tokens a day, counted over a rolling 24 hours. One answer costs about 3,500 tokens, counting the evidence and the model's reasoning. So a full run of train and the frozen set (53 answers) uses most of a day's allowance. The writer's disk cache makes reruns with unchanged evidence free. When the shipped prompt was restored, both sets came back from the cache byte-identical to the scored revision-1 outputs. The frozen sets are unchanged from v1. Steps 2–4 have to win back the train losses with general mechanisms: the LLM writer for answers, anchor-first retrieval for "the day of X", and claim chains for "has / still".

## Writer on OpenRouter

The Groq writer runs above (`openai/gpt-oss-120b`) are kept as history. They are not the reported v2 result. The step 2 runs used step 2 retrieval. The run after step 3 was stopped part-way at Groq's daily token cap and is labelled partial in the scoring log. The final v2 answer numbers are to come from one complete pass of train and the frozen set with one model, after retrieval and the planner are final; that pass has not been run yet. The judge is unchanged: Qwen `qwen/qwen3.8-27b` on Groq, with its own quota and from a different model family.

### Model

`GET https://openrouter.ai/api/v1/models` listed 458 models. Six end in `:free` and accept JSON output (`response_format` or `structured_outputs`):

| model | context | max output | structured outputs |
|---|---|---|---|
| `dots-studio/dots-3-note-preview:free` | 512,000 | 460,800 | yes |
| `apodex/apodex-1.1-mini:free` | 262,144 | 235,929 | yes |
| `google/gemma-4-26b-a4b-it:free` | 262,144 | 32,768 | no (JSON mode only) |
| `google/gemma-4-31b-it:free` | 262,144 | 32,768 | no (JSON mode only) |
| `nvidia/nemotron-3-super-120b-a12b:free` | 262,144 | 235,929 | yes |
| `liquid/lfm-2.5-2.6b:free` | 65,536 | 8,192 | yes |

Chosen: `nvidia/nemotron-3-super-120b-a12b:free`. It is not from the Qwen family. It supports structured outputs as well as JSON mode, and it is a full-size model. The others are a preview, a "mini", JSON mode only, or 2.6B. Its 262k context is far more than 8 trimmed records need; a request is about 2–3k tokens. The writer asks for `response_format: json_object` (`LLM_JSON_MODE=1`) and still parses leniently.

### Limits

From OpenRouter's limits page, read on 2026-10-12, and from `GET /api/v1/key` for this key:

- Free (`:free`) models allow **20 requests a minute**.
- They allow **50 requests a day** when less than 10 credits have been bought in total, and **1,000 a day** at 10 credits or more. The day is a UTC day, so the count resets at 05:30 IST.
- The tier depends on credits bought in total, not on the current balance. A negative balance can return 402 even on free models.
- This key reports `is_free_tier: true` and `free_model_daily_requests` with a limit of 50.

One pass is 53 questions (27 train, 26 frozen), plus any retries, so it cannot finish within one UTC day at 50. A smoke test of one train question used one request; that answer is cached and reused by the full pass.

### Client changes (not OpenRouter-only)

- `HTTP-Referer` and `X-Title` are sent only when `LLM_HTTP_REFERER` and `LLM_X_TITLE` are set.
- The key is read from `LLM_API_KEY`, or from `OPENROUTER_API_KEY` when `LLM_API_KEY` is blank. It is read from the environment or `.env` and never printed or logged.
- JSON is found inside prose or a code fence. An unreadable reply is asked once more. If that also fails, the deterministic writer answers, and the answer is counted as a fallback (strict mode stops the run instead).
- On 429 or 5xx the client honours `Retry-After` (up to 120 s), otherwise backs off. A 429 that reports the quota is spent until a reset more than 5 minutes away stops at once with the reset time, instead of retrying into the cap. `LLM_REQUESTS_PER_MINUTE=15` spaces requests under the 20-a-minute limit.
- Counters: requests, retries, 429s, 5xx and parse retries are printed per run and written per question to the writer log. `CANDOR_WRITER_LEDGER` writes one line per HTTP attempt (time, model, outcome), so totals add up across restarts.

### Cache key

The key is a sha256 of: the prompt hash, the endpoint host, the model id, the question, `as_of`, and a sha256 of the exact user message. That message holds the owner, the time and every evidence block as sent. So an answer from another model, prompt, endpoint or evidence set cannot be read back. The endpoint host is new: before, the same model id on two providers would have shared entries. `tests/test_writer.py` checks that another model, or another endpoint, asks again.

### Fewer tokens per question

The writer now reads the top **8** trusted retrieved records (was 10). Each record is cut to **180 words** (was 350): its first 40 words plus the 40-word windows that share the most question terms, in their original order, with `[...]` at the gaps. Shorter records go in whole. `retrieved` is unchanged; only what the model reads is smaller. The cut changes every evidence hash, so no Groq-era answer can come back from the cache.

### Where step 2 stands

Step 2 is closed as built and checked on a partial sample. No complete judged pass of train and the frozen set exists with the current settings, because of the free tiers' daily limits. No improvement below is claimed as proven.

What was built:

- The writer returns structured JSON: `answerable`, `answer`, `source_ids`.
- Source ids are kept only when they name a record the model was shown.
- Deleted and quarantined records never reach the model.
- With no key, or on any rejected reply, the deterministic writer answers. `test_no_settings_uses_the_deterministic_writer` and `test_bad_json_falls_back` test those two paths; `test_unreadable_reply_is_retried_once_then_falls_back` tests the retry before the fallback.
- Replies are cached on disk, keyed by prompt hash, endpoint, model, question, time and the exact evidence.

Two sets of writer numbers exist. They use different models and settings, so neither is a v2 result.

**A. Complete pass, older settings, different model.** `openai/gpt-oss-120b` on Groq; step 2 retrieval; top 10 records at up to 350 words; prompt revision 1. Every answer came from the model, with no fallbacks. This is the "revision 1" row above.

| | train (n=27) no judge / Qwen judge | frozen (n=26) no judge / Qwen judge |
|---|---|---|
| after step 1, deterministic writer | 19/27 = 70.4 / 17/27 = 63.0 | 6/26 = 23.1 / 4.5/26 = 17.3 |
| A: gpt-oss-120b, revision 1 | 25/27 = 92.6 / 22.5/27 = 83.3 | 17/26 = 65.4 / 16.5/26 = 63.5 |

**B. Partial sample, current settings.** `nvidia/nemotron-3-super-120b-a12b:free` on OpenRouter; retrieval as of the last step 3 run before this section; top 8 records at up to 180 words; prompt revision 1. Strict mode was on, so every answer came from the model or its cache. `retrieved` was byte-identical to the deterministic run on every answered question. The comparison row is the deterministic writer on the same retrieval and the same questions.

| | train (n=27, complete) no judge / Qwen judge | frozen (14 of 26 answered) no judge / Qwen judge |
|---|---|---|
| deterministic writer, same retrieval | 18/27 = 66.7 / 16/27 = 59.3 | 3/14 = 21.4 / 2/14 = 14.3 |
| B: Nemotron | 25/27 = 92.6 / 23.5/27 = 87.0 | 10/14 = 71.4 / 9.5/14 = 67.9 |

Counts are strict scores: a partial answer counts as half. Train for B is all 27 questions. An earlier summary said 18 train answers, but 18 was the number of requests in the per-attempt log, not the number of answers. The other answers came from the writer cache, written by the second process described below with the same model. The cache key holds the prompt hash, endpoint, model and a hash of the exact evidence, so a cached answer is read back only when all of those match.

On train, B's no-judge failure is `MEM-TR-12` (it abstained on an answerable temporal question). The judge also marks down `MEM-TR-04`, `MEM-TR-08` and `MEM-TR-10` (each leaves out a detail), and `MEM-TR-26` (it states a signing date the records do not give). The 14 frozen questions are the first 14 by file order, not a chosen subset. Twelve frozen answers are missing, so B's frozen number is not comparable with A's 26-question score.

How the sample stopped. Two wrapper processes were running against the one key: the Groq-era run (whose child processes read `.env` again on each restart, so after the switch they called OpenRouter too) and the OpenRouter pass. The Groq-era wrapper was meant to be stopped at the switch and was not. Between them they used the 50-a-day allowance. Only the OpenRouter pass wrote the per-attempt ledger, which is why the key reported 54 requests used while the ledger shows 18. Both processes used the same model, prompt, settings and cache, so the answers above are valid model answers; but the request and retry totals for the sample are incomplete. Both are now stopped. From here on, runs are not left looping in the background: every run is started once, and all Python processes are listed with their command lines before and after any long run.

Judge cost of the sample: 7 Qwen calls; every other verdict came from the judge cache.

## Step 3: deterministic retrieval

Retrieval uses no model. Every number below is the share of questions where each needed group has a member in the top 10, scored with the deterministic writer.

### Anchor-first ("after / before / since / following / until X")

`hops.find_anchor` reads the anchor phrase and its direction from the question. It also reads an offset when one is given ("the day after X"). `hops.resolve` finds the anchor event in the records visible at the question time. For a day anchor, it takes the first of the top three hits that is a calendar entry or states a date on or after its own; otherwise it takes the top hit, using the meeting start for a meeting. Records on the wrong side of the anchor are scored at 0.6. The anchor record is added near the top. The best matches for the rest of the question on the right side of the anchor are added below it: "after" has no upper bound, and "before" looks back 7 days.

| run | change | train | probe | frozen |
|---|---|---|---|---|
| step 2 rev 1 | none (baseline) | 92.0 | 57.1 | 73.9 |
| first anchor | "after" window 3 days, anchor preferred event records | 88.0 | — | — |
| general anchor | rules above, `chain_width + 2` added records at 0.8 of the top score | 92.0 | 64.3 | 73.9 |
| lighter anchor | `chain_width` added records at 0.7 | 96.0 | 64.3 | 73.9 |

The first version broke `MEM-TR-12` ("how many days after the Acme call…"), because the 3-day window cut off the reply. The general version still broke it. The anchor resolves to the "Acme call prep" calendar entry, two hours before the call, so the call's own transcript segments counted as "after" it. Added at 0.8, they pushed the proposal email out of the top 10. Added at 0.7, they rank below records the ordinary ranking already scored well. `MEM-TR-25` and its probe paraphrase now pass. The frozen score did not move, and 4 frozen questions have a different top 10.

### Second hop for joins

`hops.join_query` takes the top five trusted records, one per parent. It adds to the question up to six terms that at least two of those records share, rarest first; a term found in only one record is left out as noise. A second word search runs with that query. The two rankings are merged by reciprocal rank (k = 60), with the second given half weight, and the per-parent cap is applied again. This runs on every question, with no gate on the question's wording.

| run | change | train | probe | frozen (top 10 / top 20) |
|---|---|---|---|---|
| lighter anchor | before the join | 96.0 | 64.3 | 73.9 / 74 |
| join at the end | merged after every other step | 96.0 | 78.6 | 73.9 / 74 |
| keep top five | top five of the first search fixed | 96.0 | 64.3 | 73.9 / 74 |
| join first | merged before the anchor, thread and calendar steps | 92.0 | 78.6 | 69.6 / 74 |
| hop records keep their place | records added by the anchor, thread or calendar steps keep their first-ranking position in the second ranking | 96.0 | 85.7 | 73.9 / 78 |

Shipped: the last row. "Join at the end" broke `MEM-PR-25` (the day of a trip). The calendar entry for that day was added by the calendar step, not found by words. The second search could not find it either, so the merge pushed it out. A record a step added was never a word match, so the second search has no say over it. Probe top-20 recall went from 79% back to 100%.

Still failing: `MEM-TR-26` and `MEM-PR-26` ("has Acme signed / given us a yes"). The acknowledgement says neither word. Also `MEM-PR-21` ("what caused the date to move"): the cause is in records that share few words with the question.

### Open items

The step runs when the question asks what is open, outstanding, pending, owed or still to do. `hops.commitments` reads trusted records and finds sentences that either promise a task ("I'll / we'll / let me" plus a task verb) or request one ("can you / please" plus a task verb). It skips:

- sentences with a negation;
- assistant chats (ChatGPT, Codex) and calendar entries;
- mail from role addresses (newsletters, partners@, no-reply).

A request counts as the owner's to do only when it reaches the owner directly: a DM or two-person thread, or one that names the owner. `hops.completed` closes a commitment when a later record by the person who owes it shares at least two of its terms and says it happened (sent, attached, done, here's…). Names are compared without the email address, so a promise made in a meeting can be closed by an email. If the question asks what *I* owe, only the owner's debts are kept. The open items are added below the anchor records and kept in place by the join step.

On the data as of Sep 18 it finds 45 commitments, and 26 of them are open. I read the list by eye: the open ones are real tasks, and the cases above are why each skip exists.

| run | train | probe | frozen (top 10 / top 20) |
|---|---|---|---|
| hop records keep their place | 96.0 | 85.7 | 73.9 / 78 |
| + open items | 96.0 | 85.7 | 73.9 / 74 |

No train or probe question lists open items, so the development sets can't measure this step. Only `MEM-TR-06` triggers it, and it still passes. Frozen top-20 recall fell from 78% to 74%, which suggests the step fires on some frozen questions that aren't about open items. I left the trigger as it is: narrowing it because of a frozen number would be fitting to the frozen set. Frozen top-10 did not change.

### A cache bug the hop tests found

`hops.tokens` first cached a record's words by id alone. An edited Slack message keeps its id, but its text depends on the question time, so the cache could return words from the wrong time. It is now keyed on id and text. Scores were the same after the fix.

### Status questions read the newest reply in a thread

`MEM-TR-26` ("Has Acme signed the contract?") placed the acknowledgement email 11th. The thread step had already added it, as a reply to the proposal email at 0.98 of the proposal's score, and the merge left it just below the cut. The newest records that mention Acme are go/no-go meeting segments, so "the newest record sharing the question's rarest terms" would not have found it; that idea was dropped before coding. The rule that does find it is about threads, not words. When the question asks for a current state (it starts with has / have / is / are / did / does / do, or says yet / still / so far / status), the newest reply in an email thread that a top hit belongs to is scored just above that hit (×1.01 instead of ×0.98). The newest message in a thread is its current state. It names no person, company or word from the data. `tests/test_hops.py` checks both the status case and the ordinary case.

| run | train | probe | frozen (top 10 / top 20) |
|---|---|---|---|
| + open items | 96.0 | 85.7 | 73.9 / 74 |
| + newest reply for status questions | 100 | 85.7 | 73.9 / 74 |

Actions were rescored, because "message from memory" uses retrieval: unchanged on every set.

`MEM-PR-26`, the probe paraphrase ("Did Acme Freight give us a yes on the deal yet?"), still fails. No email reaches its top 20, because "a yes on the deal" shares no words with "proposal", so the thread rule never fires. Closing that gap would mean fitting to the probe wording, so it was left failing.

`MEM-TR-25` ("the day of X") is handled by the general anchor step above. The anchor phrase and its offset are read from the wording ("the day of", "the day after", "after", "before", "since", "following", "until"). The anchor event is found by an ordinary search, and that day's calendar entries come from the calendar step. Nothing in it names the train event.

### Checks on the final step 3 retrieval

Each set was run twice with the deterministic writer. The two outputs are byte-identical on train, probe and frozen. No question in any of the three sets has a forbidden record in its top 10, and none is retrieved in any top 20.

Per question, against retrieval before step 3 (step 2, revision 1):

| set | now passes | now fails |
|---|---|---|
| train | `MEM-TR-25` (temporal, anchor), `MEM-TR-26` (status thread) | none |
| probe | `MEM-PR-25` (temporal, anchor), `MEM-PR-02`, `MEM-PR-05`, `MEM-PR-10` (join) | none |
| frozen | none | none |

Frozen retrieval by category (top 10, pass/fail only; 3 abstention questions are not scored):

| category | ids |
|---|---|
| anchor_relative | `MEM-V2-02` pass, `MEM-V2-18` pass, `MEM-V2-26` pass |
| as_of_time_travel | `MEM-V2-11` pass, `MEM-V2-24` pass |
| cross_source | `MEM-V2-19` pass |
| disagreement | `MEM-V2-10` pass |
| multi_hop | `MEM-V2-21` FAIL |
| open_items | `MEM-V2-05` pass, `MEM-V2-06` FAIL, `MEM-V2-23` FAIL |
| ownership | `MEM-V2-13` FAIL |
| reported_speech | `MEM-V2-01` FAIL |
| single_fact | `MEM-V2-04` pass, `MEM-V2-14` pass, `MEM-V2-25` FAIL |
| temporal | `MEM-V2-03` pass, `MEM-V2-20` pass |
| uncertain_speaker | `MEM-V2-22` pass |
| work_app | `MEM-V2-15` pass, `MEM-V2-16` pass, `MEM-V2-17` pass |
| yes_no | `MEM-V2-12` pass |

No frozen join, "after X" or open-items question improved. The three anchor questions passed before step 3 and still pass. The multi-hop question and two of the three open-items questions failed before and still fail. No frozen question changed in either direction, at top 10 or at top 20.

**The step 3 gains are fitted to the development sets.** The probe was used to choose between the join variants (78.6 against 85.7), and every mechanism was designed from a train or probe failure. So the probe is no longer a held-out check, and the train and probe gains do not show that the mechanisms generalise. The only held-out evidence is the frozen set, and it did not move. The frozen revision allowed after this report was not used. Building one from failing frozen ids and categories would be tuning to the frozen set, and nothing in the development sets points to a change.

## Step 4: actions

All numbers are full-match pass rates from `eval_harness/score_actions.py`. The development sets are train (12), extra (33) and phrasing (10). The independent phrasing set (10) and the frozen set (15) are reported as numbers only.

**Which sets were looked at.** While building the planner, I read the commands, expected actions and outputs of train, extra and phrasing. For the independent phrasing set and the frozen set, only scores were printed. But the frozen action set was written earlier in the same working session by the same assistant, so its commands were already known: for example, that Gary Holm has no address. The step 4 work also targets the kinds of command it covers (channels named by a word, people outside the directory, meetings with several people, "open X"). **So the frozen 60.0% (9/15) is a development score, not a held-out result.** The README says the same.

### Resolver rules (no model)

| run | change | train | extra | phrasing | independent | frozen |
|---|---|---|---|---|---|---|
| after step 3 | none | 91.7 | 90.9 | 100 | 100 | 26.7 |
| rules | the four changes below | 100 | 97.0 | 100 | 100 | 60.0 |
| reference needs no verb | a phrase with a verb is the message, not a thing to look up | 100 | 100 | 100 | 100 | 60.0 |
| names and bodies | a full name no longer hides other first names; "let X know …" and "X: …" bodies | 100 | 100 | 100 | 100 | 60.0 |

The four changes:

- **Message from memory.** "Email John the corrected NRR" gives no words to send; it names a thing. The resolver asks memory "What is the corrected NRR?" at the command's time and sends the answer. If memory cannot answer, it asks instead of sending. This puts back, as a general rule, the "corrected NRR" lookup removed in step 1. The answer depends on the time: 112% at noon on Sep 16, after Ben's correction, and 118% at 10:00, before it.
- **Channels from a word.** The recipient words after the verb are matched against channel names, then against channel topics from `channels.json`. "Everyone" and "the whole company" match the company-wide channel by its topic. One match sends; two or more ask which channel. A recipient that names a person in the directory is never read as a channel.
- **People outside the directory.** A capitalised name in a recipient slot (after the verb, "with", "cc", "to", "and" or a comma) that is not in the directory is looked up in trusted records visible at the command's time. The address must sit within 80 characters of the name and start with the first name. One address is used. Several, or none, ask. A name never seen gets "I don't know who … is."
- **"Open X".** X opens if it is an app on a fixed list of common apps. If trusted records mention it, the command becomes a memory question; otherwise it asks what to open.

Meetings with several people already worked for first names. "John, Marcus and Sarah Kim" failed because one full-name match hid the first names; that is fixed in the last row.

### Model slot reader

`candor/slots.py` sends the command, as data, to the configured model (`LLM_*`) with no tools. The prompt asks only for labels: intent, to, cc, when, length, event, about, say, app. Every label must be words copied from the command, or the whole reply is refused and the rules read the command. The labels are written back as one plain command per action, and the same deterministic resolver handles them. So the model never chooses a person, channel, event, address or time. The checks for planted instructions, destructive commands and blocked addresses run before the model is called. A question, or an "other" intent, goes to the rules. Replies are cached by prompt hash, model and command. `CANDOR_SLOTS=off` turns the reader off.

Development was done on `openai/gpt-oss-20b`, because Groq limits each model separately and the 120b model's tokens were needed for answers. Strict mode was on, and no run fell back.

| run | change | train | extra | phrasing |
|---|---|---|---|---|
| slots prompt 1 | as above, with a `lookup` label for "a fact to look up" | 91.7 | 84.9 | 80.0 |
| slots revision 1 | `lookup` removed; `about` added. Whether a phrase names a thing is decided in code, by the same no-verb rule the resolver uses | 83.3 | 87.9 | 100 |
| + code fixes | "move" reads the new time from `to` when `when` is empty; an `about` the command never introduced with "about" and that names a thing is a lookup | 100 | 100 | 100 |

Prompt 1 failed because the model put "the corrected NRR" under words to send, and it dropped meeting topics. Revision 1 is the only prompt change. The fixes after it are in code, so the model is not asked for judgements the rules already make. The prompt names nobody from the data, and `tests/test_slots.py` checks that.

## Final pass

Run once, after retrieval and the planner were final, at commit `de25c09`.

- **Answers:** `nvidia/nemotron-3-super-120b-a12b:free` on OpenRouter, prompt revision 1, top 8 records at up to 180 words, strict mode. Every answer came from this model or its cache, with no fallbacks. Requests: 47 (6 train, 20 frozen, 21 holdout), with 1 parse retry, no 429s and no 5xx errors.
- **Judge:** Qwen `qwen/qwen3.8-27b` on Groq. Strict scores; a partial answer counts as half.
- **Actions:** the rules only, with no model (`CANDOR_WRITER=deterministic`), so they are deterministic and make no requests. The slot reader is not part of the reported numbers.
- **Processes:** each set ran once in the foreground, and the process list was checked before and after.

The frozen set is a development set (see above). The holdout is the only set the code was not shaped on.

| memory | retrieval (top 10) | answers, no judge | answers, Qwen judge |
|---|---|---|---|
| train (27) | 25/25 = 100% | 25/27 = 92.6% | 24.5/27 = 90.7% |
| frozen v2, development (26) | 17/23 = 73.9% | 18/26 = 69.2% | 16/26 = 61.5% |
| **holdout (21)** | **10/18 = 55.6%** | **9/21 = 42.9%** (95% CI 25–67%) | **7/21 = 33.3%** (95% CI 15–56%) |

No set has a forbidden record in its top 10. The judge marks down train `MEM-TR-04`, `MEM-TR-08`, `MEM-TR-10` (partial) and `MEM-TR-12` (abstained). On the frozen set the 11 judged misses are `MEM-V2-01`, `-03`, `-04`, `-06`, `-10`, `-12`, `-13`, `-15`, `-21`, `-23` and `-25`.

Holdout by category, Qwen-judged answers (retrieval in brackets, where scored):

| category | answers | retrieval |
|---|---|---|
| abstention | 1/3 | (not scored) |
| anchor_relative | 0/1 | 0/1 |
| as_of_time_travel | 2/2 | 2/2 |
| count | 0/1 | 1/1 |
| cross_source | 0/2 | 2/2 |
| disagreement | 0/1 | 0/1 |
| knowledge_update | 1/1 | 1/1 |
| multi_hop | 0/2 | 0/2 |
| open_items | 0/2 | 0/2 |
| reported_speech | 0/2 | 0/2 |
| single_fact | 1/1 | 1/1 |
| work_app | 1/2 | 2/2 |
| yes_no | 1/1 | 1/1 |

| actions | pass | argument accuracy |
|---|---|---|
| train (12), extra (33), phrasing (10), independent (10) | 100% each | 100% each |
| frozen v2, development (15) | 9/15 = 60.0% | 81.8% |
| **holdout (14)** | **9/14 = 64.3%** | **83.9%** |

What this shows. The development sets overstate the system. On the holdout, retrieval finds the evidence for about half the answerable questions. It misses every question in the categories step 3 targeted ("after X" 0/1, multi-hop joins 0/2, open items 0/2), plus reported speech (0/2) and disagreement (0/1): 0 of 8 retrieved. These match the frozen failures, so they are general weaknesses, not a quirk of one set. Where retrieval did find the evidence, the judged answers still miss both cross-source questions, the count question and one work-app question. Two of the three not-answerable questions are scored wrong, one of them only by the judge. With 21 and 14 items the intervals are wide. The holdout number is a rough estimate of the hidden-set score, and it is the one to quote.

v1 on the same holdout (tag `v1-submitted`, its own no-key answerer, same scorers and judge): retrieval 10/18 = 55.6%, answers 3/21 = 14.3% with no judge and 2/21 = 9.5% judged. So v2's holdout gain comes from the answer writer. Retrieval is no better than v1 on unseen questions.

### Which layer loses each question

`scratch/diagnose.py` retrieves 50 deep. For each needed group it records the best rank and whether the writer was shown it.

| | needed evidence not in the top 50 | in the top 50 but below 10 | shown, writer misanswered | wrong abstention | correct |
|---|---|---|---|---|---|
| frozen (26) | 6 | 0 | 5 | 0 | 15 |
| holdout (21, counts only) | 8 | 0 | 4 | 2 | 7 |

Nothing sits between ranks 11 and 50, so re-weighting the ranking cannot help. On the frozen set, 5 of the 6 never-found records are meeting turns in a meeting that is already in the top 10. They are short spoken replies that carry none of the question's words, which were in the previous turn ("Forty-two, I think, last time…" one turn after "Stockton's six dispatchers"). The sixth is a Slack promise with no "I'll" ("👍 will send the final product slide tonight"), which the open-items detector does not read. In 4 of the 5 misanswered frozen questions, the missing figure or word was in the excerpt the model read, so the 180-word cut is not the cause. The model leaves out specifics or gives one side of a disagreement.

## Meeting turns read as a conversation (tried, not shipped)

**Outcome: reverted.** Scored once on the holdout during the research below, this change lowered holdout retrieval from 10/18 to 9/18. That cancels its net gain of one on the 62 development questions, so it was taken out of retrieval. The writer change in the next section gives the writer the same replies without moving anything in the top 10. The diff is kept outside the repository. What follows is the record of what was tried.

A meeting is a conversation, and a reply often holds the answer without the words of the question it answers. Two changes, both deterministic:

- **Turn context.** Each segment is also searched with the turn before it. Its score is the higher of its own score and 0.8 × the exchange's score. With no discount, the reply outranked the turn that holds the matched words, and train fell to 84%. With the discount, a reply gains only when its own words are weak.
- **Follow-ups.** When one of the top five meeting hits asks a question, the next two turns are added just below it (0.75 and 0.70 of its score).

Both were measured on train, probe and frozen with retrieval only, deterministic writer:

| variant | train (25) | probe (14) | frozen (23) | total (62) |
|---|---|---|---|---|
| before (step 3 final) | 25 | 12 | 17 | 54 |
| turn context, no discount | 21 | 9 | 19 | 49 |
| turn context, ×0.8 | 25 | 11 | 19 | 55 |
| + follow-ups (shipped) | 25 | 11 | 19 | 55 |
| + adjacent turns, or follow-up replies, not counted against the 3-per-meeting cap | 23 | 11 | 20 | 54 |

Gained: `MEM-V2-21` (the dispatcher count) and `MEM-V2-25` (Acme's success criteria), both answered in the turn after a retrieved one. Lost: `MEM-PR-08`. The reply to the matched turn takes a top-10 place, and `MEM-TR-08`'s probe paraphrase loses its third evidence record to rank 11. The cap exemption fixed `MEM-V2-13`, but it pushed out `MEM-TR-12` and `MEM-TR-26`, which sat at ranks 9–10, so it was dropped. Each extra meeting turn costs another record its place in a fixed top 10. The list already carries unrelated Slack messages, so the next gain is in pushing those out, not in adding more.

Follow-ups changed no score here. Their point was to give the writer the reply to a matched question, and the writer change below does that directly.

Checks at the time: two runs per set were byte-identical on train, probe and frozen, with no forbidden records in any top 10 or top 20, and actions unchanged.

## After the final pass: research, a first run and a fix

Three outside reviews suggested the same families of change: show the writer more of each conversation, hybrid word and embedding search with rank fusion, a cross-encoder reranker, model-driven multi-step retrieval (IRCoT, GraphRAG), a commitments table, extract-then-answer prompting, and a support check before answering. Each was measured, or ruled out by the rules, before any code changed. The research scripts printed only totals for the holdout, but the holdout scores were seen while choosing. It was reported as is, so it is no longer an untouched set.

### What was measured

**Hybrid search and reranking (retrieval only, top 10, n = 25 / 14 / 23 / 18).** Rank fusion of BM25 with `BAAI/bge-small-en-v1.5` lost 3 train questions and 2–4 frozen ones. On the holdout it was even with, or one question better than, the word search. A `ms-marco-MiniLM-L-6-v2` cross-encoder over the top 30 did the same. The best holdout variant (fusion plus turn context plus the reranker) was 11/18 against 10/18, while losing questions on every development set. MiniLM embeddings were no better. None put a forbidden record in the top 10. Not adopted: the gain is one holdout question at most, and retrieval would come to depend on a model.

**Not tried.** IRCoT, GraphRAG and contextual chunk summaries need a model inside retrieval, and several calls per question on a 50-a-day quota. Trust-Align needs fine-tuning. Synthetic test questions would be written from our own view of the data.

**How often the writer sees every needed record (answerable questions).** This is the upper bound for answers, separate from the retrieval score.

| evidence view | train (25) | probe (14) | frozen (23) | holdout (18) | tokens per question |
|---|---|---|---|---|---|
| top 8 records (final pass) | 22 | 9 | 18 | 10 | ~500 |
| top 10 + the nearest records of the first 3 conversations, 1,200 words each | 25 | 12 | 22 | 16 | ~2,000 |
| top 8, each followed by its next 2 records in the first 3 conversations (shipped) | 22 | 9 | 20 | 11 | ~600 |

The first and third rows use the shipped retrieval, with the promise fix below (frozen top 8 was 17 before it). The second row was measured before that fix.

### First run: wide evidence and a quote-first prompt (rejected)

The writer was shown the wide view in the second row, grouped by conversation in delivery order. The prompt asked it to copy the exact sentences it relied on before answering. This was the one prompt revision allowed after the frozen results. Run on train only (27 requests):

| train (27) | answers, no judge | answers, Qwen judge |
|---|---|---|
| final pass | 25/27 | 24.5/27 |
| first run | 24/27 | 20/27 |

Newly wrong: `MEM-TR-07`, `-09`, `-14`, `-24`, `-25`, `-26`. Only `MEM-TR-12` improved. In `MEM-TR-26` about 40 turns of one meeting filled the budget, and the newest email, which holds the answer, came last. The model took an older estimate from the meeting. `MEM-TR-24` added test counts from a neighbouring message. `MEM-TR-10` abstained with all of its evidence shown. The quote-first prompt was dropped and the prompt is back to revision 1. The frozen set and the holdout were not run with this version.

### The fix (shipped, commit `b2db20a`)

- **Writer evidence.** The top 8 records in rank order, as before. Each record in the first 3 conversations is followed by up to 2 records sent after it in the same conversation. A reply sits next to the message it answers, and nothing reorders the list. The prompt is unchanged.
- **Promises with no subject.** The open-items detector also reads a sentence that starts with "will", "gonna" or "going to" plus a task verb ("👍 will send the final product slide tonight"). Retrieval changes only on open-items questions: frozen 17/23 → 18/23 (`MEM-V2-23`). Train, probe and the holdout are unchanged.

Same model, strict mode, Qwen judge. Requests: 3 smoke-test, 16 train, 8 frozen and 16 holdout (1 parse retry). The rest came from the cache, because their evidence was unchanged. There were no fallbacks, 429s or 5xx errors.

| memory | retrieval (top 10) | answers, no judge | answers, Qwen judge |
|---|---|---|---|
| train (27), final pass → fix | 25/25 → 25/25 | 25/27 → 25/27 | 24.5/27 → 23/27 |
| frozen v2, development (26) | 17/23 → 18/23 | 18/26 → 20/26 | 16/26 → 17.5/26 |
| **holdout (21)** | **10/18 → 10/18** | **9/21 → 11/21 = 52.4%** (95% CI 36–73%) | **7/21 → 8/21 = 38.1%** (95% CI 21–58%) |

No set has a forbidden record in its top 10. Actions do not use the writer and are unchanged (holdout 9/14). On train, the judge now also marks down `MEM-TR-25` (the evening flight is left out) and `MEM-TR-26`, whose evidence gained neighbours. Compared with the final pass, the frozen misses gain `MEM-V2-05` and lose `MEM-V2-21` and `MEM-V2-25`, the two replies one turn after a retrieved question.

Holdout by category, judged answers (no-judge in brackets): abstention 1/3 (2/3), anchor_relative 0.5/1 (1/1), as_of_time_travel 2/2, count 0/1, cross_source 0/2 (1/2), disagreement 0/1, knowledge_update 1/1, multi_hop 0.5/2 (1/2), open_items 0/2, reported_speech 0/2, single_fact 1/1, work_app 1/2, yes_no 1/1.

What this shows. The gain is small: one or two holdout questions, inside wide intervals, and train lost 1.5 judged points. Holdout retrieval is still 10/18, the same as v1, and it remains the limit. Open items, reported speech, disagreement and count are 0 on the holdout.
