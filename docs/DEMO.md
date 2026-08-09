# The demo

Ninety seconds. Structure fixed (PRD-B section 6). This document is the
committed answer to B-R33 through B-R41, and `tests/test_part_b.py` asserts that
each of those ids still has an answer here.

---

## Before anything else: this demo cannot be given yet

**Gate B is unresolved.** There is no recorded real session and no
`findings/reproduced.md`. The only fixture in this repository was authored by
hand, and B-R26 forbids presenting an authored bug as a found one.

`tools/demo.py` enforces that: it exits 3 on a synthetic recording unless
`--synthetic-ok` is passed, and prints a banner when it is. The flag exists for
rehearsing the *mechanics*. It is not a way to go on stage.

What has to happen first is BUILD-PLAN days 1-2: run agents in parallel
worktrees on a real project, record every filesystem event, and find three
genuine mismatches. Then re-record the fixture from that session and this
document becomes live.

---

## The ninety seconds

| # | Step | Time | The requirement it satisfies |
|---|---|---|---|
| 1 | Problem, one sentence | 0:00–0:12 | **B-R33** — the third-party number is in the first spoken sentence, before any architecture |
| 2 | Run it, from the recorded fixture | 0:12–0:45 | **B-R34** — replay only, never a live agent |
| 3 | The number | 0:45–1:00 | **B-R35** — latency and the honest findings split, both said out loud |
| 4 | The twist | 1:00–1:20 | **B-R36** — "no model anywhere in this," then one keypress and stage 2 confirms it |
| 5 | What is next | 1:20–1:30 | **B-R37** — name the env-var gap as the verified-unoccupied one |

### Step 1 — the first sentence (B-R33)

> "When two AI agents build two halves of one feature, integration accuracy
> drops from 58% to 25% — that's third-party, not us — and both agents report
> success."

No team introduction. No "so what we built is". The number lands first.

If the merge-conflict statistic comes up in Q&A, it is only ever spoken with its
caveat attached (**B-R29**). The exact sentence lives in
`irus.receipts.MERGE_CONFLICT_STAT` so it cannot be quoted without the caveat.

### Step 2 — the replay (B-R34, B-R39)

```
python tools/demo.py fixtures/session.jsonl
```

The canvas starts **empty**. Agent A claims the API side and its surfaces
appear. Agent A releases. Agent B claims the web side. At the moment agent B
releases — and not one event before it — one dashed red arc appears between two
nodes pulled apart from each other.

Exactly one red arc (**B-R39**). This is asserted by
`test_b_r39_the_first_high_confidence_finding_follows_the_second_release`, against
the recorded event ordering rather than against intent.

### Step 3 — the number, honestly (B-R35)

Both halves out loud, in one breath, never one without the other:

> "Full sweep, five hundred files, under two seconds. On five public repos we
> got N findings; M were real, N−M were false positives. That count is in the
> repo."

**Never** say "no false positives" (**B-R25**). The ledger is
`findings/ledger.md` and it is the artifact, not an appendix.

### Step 4 — the twist (B-R36)

> "There is no model anywhere in this. It's a parser and a comparison."

Then one keypress. The replay pauses before the first `proof` event for exactly
this beat, and stage 2 confirms the finding with a 422 from the application
itself.

The claim is checked, not asserted: `test_b_r1_stage_1_imports_no_model_and_no_network`
fails the build if any model or network client appears in the stage-1 path.

### Step 5 — what is next (B-R37)

> "The env-var check is the one gap we verified nobody occupies — it's
> cross-language, near-grep cost, and it finds real unset variables in public
> repos today."

---

## Offline (B-R38)

The whole thing runs with wifi off and the laptop unplugged.

- No runtime dependencies (`pyproject.toml` has `dependencies = []`).
- The page is one self-contained file with no external reference of any kind.
- The server binds `127.0.0.1` and there is no flag to change it (B-R7).

Verified by `test_b_r5_and_b_r6_page_is_self_contained_and_offline` and
`test_b_r7_server_binds_loopback_only_and_offers_no_alternative`.

**Rehearse with wifi actually off.** A test asserting there is no URL in the
page is not the same as the machine having no network.

---

## Rehearsals (B-R40)

Ten full run-throughs before the day. Fresh terminal each time. One at a
different screen resolution. Tick these off honestly — an untried run is not a
rehearsal.

| # | Date | Wifi off | Unplugged | Fresh terminal | Resolution | Notes |
|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |
| 6 |  |  |  |  |  |  |
| 7 |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |
| 9 |  |  |  |  |  |  |
| 10 |  |  |  |  | ← different resolution |  |

Legibility at three metres is checked on the day the map is built, not on day
13 (PRD-B section 7). Stand up and walk back.

---

## Recovery lines (B-R41)

One prepared sentence per known failure mode. Say it, keep moving, do not debug
on stage.

| Failure mode | What you see | Recovery line | What you do |
|---|---|---|---|
| **Server** won't start | `Address already in use` | "Let me take that off the port it's arguing about." | `python tools/demo.py fixtures/session.jsonl --port 7346` |
| **Port** already bound by a previous rehearsal | page never loads | Same as above. | Kill it first: `lsof -ti:7345 \| xargs kill` |
| **Browser** opens blank or on the wrong tab | white page | "The map's local — one refresh." | Reload. Replay-on-connect rebuilds full state (B-R4), so a refresh is always safe. |
| Canvas stays **empty** through the replay | no nodes appear | "The receipt is the product; the map is the pretty version." | Ctrl-C, then `irus check --root fixtures/synthetic-checkout --no-baseline`. The terminal receipt says everything the map does. |
| Replay runs too fast to narrate | arc appears early | "Let me take that again more slowly." | `--speed 4` |
| Stage 2 refuses | `refused` in the proof line | "That's the safety rail doing its job — it won't execute without a rollback it can verify." | This is a feature. Show the refusal, explain B-R11, move on. |
| Someone asks "is this a model?" | — | "No model anywhere in the verification path. Here's the test that fails the build if one appears." | `pytest tests/test_part_b.py -k no_model` |
| Someone asks about false positives | — | "Here's the count." | Open `findings/ledger.md`. Never claim zero. |

---

## The rules that do not bend on stage

Restated because stage pressure is exactly when they get bent:

- **B-R26** — never plant a bug and present it as found.
- **B-R28** — never demo a live agent. Slow, nondeterministic, will not produce
  the bug on cue.
- **B-R25** — never claim zero false positives. Publish the count.
- **B-R27** — never weaken a check to make a case pass. Fix the check and say so.
