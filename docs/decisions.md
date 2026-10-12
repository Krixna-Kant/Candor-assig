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
| after step 1, deterministic writer | 70.4 / 63.0 | 23.1 / 17.3 |
| A: gpt-oss-120b, revision 1 | 92.6 / 83.3 | 65.4 / 63.5 |

**B. Partial sample, current settings.** `nvidia/nemotron-3-super-120b-a12b:free` on OpenRouter; retrieval as of the last step 3 run before this section; top 8 records at up to 180 words; prompt revision 1. Strict mode was on, so every answer came from the model or its cache. `retrieved` was byte-identical to the deterministic run on every answered question. The comparison row is the deterministic writer on the same retrieval and the same questions.

| | train (n=27, complete) no judge / Qwen judge | frozen (14 of 26 answered) no judge / Qwen judge |
|---|---|---|
| deterministic writer, same retrieval | 66.7 / 59.3 | 21.4 / 14.3 |
| B: Nemotron | 92.6 / 87.0 | 71.4 / 67.9 |

On train, B's no-judge failure is `MEM-TR-12` (it abstained on an answerable temporal question). The judge also marks down `MEM-TR-04`, `MEM-TR-08` and `MEM-TR-10` (each leaves out a detail), and `MEM-TR-26` (it states a signing date the records do not give). The 14 frozen questions are the first 14 by file order, not a chosen subset. Twelve frozen answers are missing, so B's frozen number is not comparable with A's 26-question score.

How the sample stopped. Two wrapper processes were running against the one key: the Groq-era run (whose child processes read `.env` again on each restart, so after the switch they called OpenRouter too) and the OpenRouter pass. The Groq-era wrapper was meant to be stopped at the switch and was not. Between them they used the 50-a-day allowance. Only the OpenRouter pass wrote the per-attempt ledger, which is why the key reported 54 requests used while the ledger shows 18. Both processes used the same model, prompt, settings and cache, so the answers above are valid model answers; but the request and retry totals for the sample are incomplete. Both are now stopped.

Judge cost of the sample: 7 Qwen calls; every other verdict came from the judge cache.
