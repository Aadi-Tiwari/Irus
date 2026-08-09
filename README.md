# Irus

Catches the bug that happens between two AI coding agents.

When two agents each build one half of a feature, both finish, both report
success truthfully, and both halves compile. The disagreement between them
belongs to nobody, survives code review, and merges clean. Irus finds that
disagreement before the merge, proves it by executing it, and draws it.

```
$ irus check
irus  baseline a1b2c3d (merge-base)  ·  876 files  ·  1586 ms

FAIL  seam-087f32a0  POST /api/checkout    payload mismatch    high
      producer  api/routes.py:25 declares json body {"amount": "int", "email": "str"}
      consumer  web/Checkout.tsx:15 declares multipart body with ['total', 'user_email']
      consumer sends multipart but producer declares json (CheckoutRequest)
      proof     ✗ schema → 422  body: expected json, received multipart; email: field required

1 finding this session, 1 high-confidence
      false positives are not zero; the measured split is in findings/ledger.md
```

Exit code 1. It works as a merge gate.

---

## State of this repository

This branch implements **PRD-B** — the non-functional half: determinism, offline
operation, execution safety, the event-log contract, the interfaces, the
integrity rules, and the measurement plan. `docs/PART-B-CONFORMANCE.md` maps
every B-Rn to where it lives and which test covers it.

**The premise is not yet proven.** Gate B (three real mismatches reproduced from
a recorded parallel-agent session) is unresolved, and the build plan is explicit
that zero reproduced means stop. See `findings/reproduced.md`. The only fixture
here was written by hand, is marked `SYNTHETIC`, and the demo runner refuses to
replay it without an explicit acknowledgement.

What exists is the machinery. What is missing is the evidence.

---

## Install

```bash
pip install -e .          # no runtime dependencies, by design (B-R5)
```

Python 3.11+. Nothing is fetched at runtime, ever.

## Use

```bash
irus check                     # sweep, print receipts, exit 1 on a high-confidence finding
irus check --prove --yes       # add stage-2 execution proof (opt-in, B-R12)
irus watch                     # live local page on 127.0.0.1:7345
irus baseline                  # recompute the merge-base baseline
irus ledger <repo>...  --write # unfiltered run, writes findings/ledger.md
irus suppress <id> "<reason>"  # silence a false positive; a reason is required
irus replay <log> --digest     # reconstruct state from an event log
```

## How it works

**Stage 1 detects** without running anything. A stdlib `ast` pass over the
FastAPI side gives route, method, and the Pydantic request shape. A brace-matching
scanner over the React side gives fetch target, method, and body construction.
The two are compared. Pure function of the working tree: same input, same output,
no model, no network, no clock, no randomness.

**Stage 2 proves** by executing. Tier 1 builds the request and validates it
against the declared schema without sending it. Tier 2 sends it through the
framework's own test client inside a transaction that rolls back — so the
application returns the verdict, not our checker. Five hard rails guard it, each
a raised exception rather than a warning: no non-localhost host, no real mutating
request over the wire, no mutation without a rolling-back transaction, a
row-count check after every run that discards the verdict if anything changed,
and opt-in consent on first use.

**The baseline** is anchored to the git merge-base, checked out into a temporary
worktree, swept, and cached by SHA. Everything pre-existing becomes invisible, so
a first run on a large messy repo reports nothing until you change something.

**The log** is one append-only JSONL file. It is the demo recording, the test
fixture, and the replay source; there is no second format. The page rebuilds its
entire state from the log on every connect, which is why a refresh — or a laptop
lid closing — is always safe.

## Repository map

| Path | What |
|---|---|
| `irus/check.py` | The sweep. No model, no network — asserted by test |
| `irus/extract/` | Producer (`ast`), consumer (scanner), env vars |
| `irus/findings.py` | Confidence tiers, suppressions, the both-paths rule |
| `irus/baseline.py` | Merge-base worktree, SHA cache, session diff |
| `irus/prove.py` | Stage 2 and its five safety rails |
| `irus/events.py` | The append-only log and the replay reducer |
| `irus/server.py` | `http.server` + SSE, loopback only, replay on connect |
| `irus/page/index.html` | The map. One file, no build step, no external request |
| `irus/ledger.py` | The measurement artifact |
| `tests/test_part_b.py` | 67 tests, one per PRD-B requirement |
| `docs/PART-B-CONFORMANCE.md` | Every B-Rn: status, location, covering test |
| `docs/DEMO.md` | The ninety seconds, the rehearsal log, the recovery lines |
| `findings/ledger.md` | Unfiltered run over five real public repositories |
| `findings/reproduced.md` | Gate B. Currently empty, and that matters |

## Measured

Unfiltered, five public repositories we did not write (`findings/ledger.md`):

| Repo | Files | Sweep | Findings | High-confidence |
|---|---|---|---|---|
| full-stack-fastapi-template | 148 | 119 ms | 19 | 0 |
| dispatch | 876 | 1586 ms | 134 | 0 |
| reflex | 894 | 2664 ms | 19 | 0 |
| redash | 861 | 1075 ms | 21 | 0 |
| flower | 58 | 231 ms | 4 | 0 |

197 findings, 0 high-confidence, so `irus check` exits 0 on all five — correct,
because none of them contains an agent-introduced seam mismatch. **None of these
rows is hand-labelled true or false yet.** That labelling is a human step and it
has not happened, so no precision figure is published. A number our own checker
labelled would measure agreement with us, not correctness (PRD-B §5.3).

Getting here required fixing four real checker bugs found by running against
those repos — listed in `docs/PART-B-CONFORMANCE.md` under "Corrections". None
was fixed by weakening output; all four were fixed in the extractor (B-R27).

## The rules

- A model may write a test. A model may never judge one.
- Never plant a bug and present it as found.
- Never claim zero false positives. Publish the count.
- Never weaken a check to make a case pass. Fix the check and say so.
- Never demo a live agent.

## Tests

```bash
pytest tests/test_part_b.py
```

Named for the requirement each covers, so a failure says which requirement broke.
