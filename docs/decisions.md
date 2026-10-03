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
