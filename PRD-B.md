# Irus PRD, Part B: Requirements, Measurement, and Delivery

Part A covers the problem, the users, and the product definition, and holds the
functional requirements A-R1 through A-R25. This part covers how it must behave,
how it gets measured, what ships when, and what was decided against.

Status: draft, Aug 9 2026. Two gates unresolved (section 8).

---

## 1. Non-functional requirements

### 1.1 Determinism

| ID | Requirement |
|---|---|
| B-R1 | Stage 1 is a pure function of the working tree. Same input, same output, always. No model, no network, no clock, no randomness |
| B-R2 | Layout positions in the map are seeded from node identity, so the same codebase renders identically every session |
| B-R3 | The baseline is anchored to a commit SHA, never to wall-clock time, so two people get identical results and the demo replays exactly |
| B-R4 | Replaying the event log from the start reconstructs identical state, so a browser refresh is idempotent |

### 1.2 Offline and isolation

| ID | Requirement |
|---|---|
| B-R5 | The entire tool functions with no network connection. No CDN, no telemetry, no accounts, no hosted service |
| B-R6 | The live page is one self-contained HTML file with no build step |
| B-R7 | No source code, file contents, or repository data leaves the machine under any configuration |

### 1.3 Safety of execution

Stage 2 runs code, so it needs real constraints rather than good intentions.

| ID | Requirement |
|---|---|
| B-R8 | Refuse to send any request to a host that is not localhost |
| B-R9 | Never issue a real POST, PUT, PATCH, or DELETE over the network |
| B-R10 | Mutating requests go through the framework's in-process test client inside a transaction that rolls back, or they do not run |
| B-R11 | Verify after every stage-2 run that the database row count is unchanged, and fail loudly if it is not |
| B-R12 | Stage 2 is opt-in by flag on first use, so nobody is surprised by their code being executed |

### 1.4 Performance

| ID | Requirement |
|---|---|
| B-R13 | Stage 1 full sweep on a repository of 500 source files completes in under 2 seconds |
| B-R14 | Incremental re-check after a single file change completes in under 200 milliseconds |
| B-R15 | Per-seam results are cached against a content hash of both sides, so a full re-run only recomputes what changed |
| B-R16 | The file watcher ignores `node_modules`, `.git`, `__pycache__`, `dist`, `.venv`, and everything in `.gitignore`, and debounces bursts |

### 1.5 Signal quality

| ID | Requirement |
|---|---|
| B-R17 | Findings carry a confidence tier. Only high-confidence findings fail the merge gate |
| B-R18 | A suppression file exists so a user can permanently silence a known false positive with a reason recorded |
| B-R19 | Every finding names both file paths and the exact disagreement, never a generic warning |
| B-R20 | On a clean checkout of a repository, session-scoped findings are zero |

---

## 2. The event log contract

One append-only JSONL file. One event per line. This is the only state that
matters; everything else is derived from it.

```json
{"t": 1723190400.12, "kind": "baseline",  "sha": "a1b2c3d", "findings": 47}
{"t": 1723190412.44, "kind": "claim",     "agent": "codex-1", "target": "api/checkout"}
{"t": 1723190480.03, "kind": "surface",   "id": "POST /api/checkout", "side": "producer", "shape": {"email": "str", "amount": "int"}}
{"t": 1723190501.77, "kind": "surface",   "id": "POST /api/checkout", "side": "consumer", "shape": {"user_email": "str", "total": "str"}, "encoding": "multipart"}
{"t": 1723190501.81, "kind": "finding",   "id": "seam-004", "seam": "POST /api/checkout", "class": "payload_mismatch", "confidence": "high", "detail": "consumer sends multipart with user_email/total, producer expects JSON with email/amount"}
{"t": 1723190504.19, "kind": "proof",     "id": "seam-004", "method": "test_client", "result": "fail", "status": 422}
```

| ID | Requirement |
|---|---|
| B-R21 | The log is append-only. Nothing is ever rewritten or deleted |
| B-R22 | Every event carries a timestamp and a kind. Unknown kinds are ignored by readers rather than fatal |
| B-R23 | The log is the demo recording, the test fixture, and the replay source. There is no second format |

---

## 3. Interfaces

### 3.1 Command line

| Command | Behaviour | Exit code |
|---|---|---|
| `irus check` | One-shot sweep, prints receipts | 0 clean, 1 high-confidence finding present |
| `irus check --prove` | Same, plus stage-2 execution proof | as above |
| `irus watch` | Starts the local server, opens the browser, streams live | runs until interrupted |
| `irus baseline` | Recomputes and caches the baseline for the current merge-base | 0 |
| `irus ledger <repo>` | Runs unfiltered against a repository and emits a labelling worksheet | 0 |

### 3.2 The page

Serves on localhost over server-sent events. Replays the full log on connect.

**Visual contract:**

| Element | Encoding |
|---|---|
| Healthy node | Neutral gray `#898781`, no colour, small |
| Broken seam | `#d03b3b` both themes |
| Orphan | `#c98500` dark, `#eda100` light |
| Active now | `#3987e5` dark, `#2a78d6` light |
| Baseline layer | Dim, thin edges, no labels, pure context |
| Session layer | Full size, colour, labels, drawn on top |
| Missing connection | Dashed red arc, endpoints pulled apart so the gap is legible |
| Node size | Blast radius, meaning how many things depend on it |
| Identity (which agent) | A ring or a filter, never the fill colour |

Palette validated all-pairs for colour vision deficiency in both themes: worst
pair in dark mode ΔE 10.2 deuteranopia, 16.9 normal vision. Light-mode amber sits
below 3:1 contrast against the surface, so it always carries a visible label.

### 3.3 MCP (P2)

Text, not pictures. `status`, `next`, `claim`, `release`. The graph is for humans;
the text is for machines.

---

## 4. Integrity rules

These are requirements, not aspirations. Violating one is a bug.

| ID | Rule | Why |
|---|---|---|
| B-R24 | A model may write a test. A model may never decide whether a test passed | Preserves "no model in the verification path" while using a model where it is genuinely good |
| B-R25 | Never claim zero false positives. Publish the count | One counterexample from a judge ends a perfection claim. A published count cannot be ambushed |
| B-R26 | Never plant a bug and present it as found | A checker tuned to a bug you seeded measures nothing |
| B-R27 | Never weaken or delete a check to make a case pass. Fix the check and say so | Gaming your own gate destroys the only thing the tool sells |
| B-R28 | Never demo a live agent | Slow, nondeterministic, will not produce the bug on cue |
| B-R29 | State the caveat on the merge-conflict statistic every time it is used | It counts conflicts git already catches, which is not our failure class |

---

## 5. Measurement plan

### 5.1 The findings ledger

The primary published artifact, committed to the repository as
`findings/ledger.md`.

Run the full checker, unfiltered, against five real public repositories. Hand-label
every finding true or false. Publish all of it, including the false positives, with
totals stated plainly.

```
repo: <name>            findings: 11    true: 3    false: 8
  seam-001  POST /api/orders payload mismatch          TRUE
  seam-002  env DATABASE_URL read, never set           TRUE
  seam-003  endpoint /health zero callers              FALSE  (called by k8s probe)
  ...
```

| ID | Requirement |
|---|---|
| B-R30 | Every published number has its false positives published beside it |
| B-R31 | Labels are recorded with a reason, not just a verdict |
| B-R32 | The ledger is regenerated, not edited, whenever the checker changes |

### 5.2 Numbers we will report

- Detection latency, measured, on a named repository size
- Findings count and the true/false split per repository
- How many of our reproduced mismatches stage 1 catches, and how many stage 2 confirms

### 5.3 Numbers we will not report

- Any accuracy figure over a corpus our own checker labelled. If our checker
  defines what counts as a failure, the measurement is agreement with us rather
  than correctness. Execution proof partly fixes this by letting the application
  decide, but third-party labelling is still required before any such number is
  publishable, and that is not a two-week item
- Any comparison against another agent tool until the harness for it is documented
  and reproducible

---

## 6. Demo requirements

Ninety seconds. Structure fixed.

| Step | Content | Requirement |
|---|---|---|
| 1 | Problem, one sentence, no team introduction | B-R33: the third-party number appears in the first spoken sentence |
| 2 | Run it live from the recorded fixture | B-R34: replay only, never a live agent |
| 3 | The number | B-R35: latency and the honest findings split, both said out loud |
| 4 | The twist | B-R36: "no model anywhere in this," then one keypress and stage 2 confirms it |
| 5 | What is next | B-R37: name the env-var gap as the verified-unoccupied one |

| ID | Requirement |
|---|---|
| B-R38 | The entire demo runs with wifi off and the laptop unplugged |
| B-R39 | The canvas starts empty and gains exactly one red arc at the moment the second agent finishes |
| B-R40 | Ten full rehearsals before the day, including one at a different screen resolution |
| B-R41 | A prepared recovery line for each known failure mode |

---

## 7. Risks

| Risk | Likelihood | Response |
|---|---|---|
| Payload shape matching turns out to be real type inference and consumes a week | High | Narrow to literal object bodies and `FormData` only. State the limit in the pitch rather than silently overclaiming |
| Findings flood a real repository | High | The baseline diff is the primary defence. If it still floods, ship confidence tiers and gate on high only |
| The canvas is empty or a hairball on stage | Medium | Two-layer render. Verify legibility at three metres on day 10, not day 13 |
| A competitor ships the same thing mid-build | Medium | Position rather than pivot. roam-code prevents and never verifies; Bernstein needs tests that already exist |
| File watcher storms on `node_modules` | Medium | Ignore list plus debounce, tested against a repo with real dependencies installed |
| SSE drops when the laptop sleeps | Medium | Replay-on-connect already handles it. Test by closing the lid |
| Stage 2 mutates real data | Low if B-R8 to B-R12 hold | Those five requirements exist entirely for this |
| The category cannot be monetised | High, long-term | Out of scope for the demo. Noted so it is not discovered later as a surprise |

---

## 8. Open questions and gates

Both gates are unresolved as of Aug 9 2026 and both are answerable in one day.
Everything downstream is contingent on them.

**Gate A: do mid-build agent worktrees actually boot?**

This is the load-bearing premise of the entire design. Static analysis is only
*necessary* if the application cannot be run mid-build. If it can be run, one
request settles the headline example and stage 1 becomes an optimisation rather
than the product.

- Worktrees do not boot: proceed as specified.
- Worktrees do boot: stage 2 is the product, stage 1 is the fast path, the pitch
  is rewritten around execution. This is a cheaper product, not a failure.

**Gate B: can three real mismatches be reproduced from our own history?**

- Three or more: proceed.
- One or two: proceed with a narrowed claim, stated in the pitch.
- Zero: stop. The premise is unproven and building does not fix that.

**Also unresolved:** cross-language payload matching cost. The canonical paper
(Wittern et al., ICSE 2017) reported 96% precision on endpoint and method and
87.9% on payload, and was never productised in the nine years since. That is
either the opportunity or the warning, and current evidence cannot distinguish
between them.

---

## 9. Release plan

| Release | Contents | Gate to enter |
|---|---|---|
| **v0.1, demo** | A-R1 to A-R4, A-R8 to A-R11, A-R13 to A-R18, plus A-R19 and A-R20 if time allows | Gates A and B passed |
| **v0.2, usable** | Confidence tiers, suppression file, second stack pair, response shape, `irus check` as a GitHub Action | v0.1 works on a repo we did not write |
| **v0.3, coordination** | Authority rule, one-owner-per-round dispatch, the ratcheted fix loop, the MCP surface | v0.2 has a real user who is not the author |
| **Deferred indefinitely** | Event relay for remote collaborators, seam pack registry, any published benchmark | Someone asks for it |

---

## 10. Decision log

Recorded so these stay decided. Each was considered seriously and rejected for a
stated reason.

| Decision | Rejected alternative | Reason |
|---|---|---|
| Verify code, not report on people | A manager-visibility "team pulse" page | Its inputs would be unverified agent claims. A dashboard built on self-reports manufactures false confidence at management altitude, which is worse than no dashboard |
| Read git and the filesystem | Parse agent session transcripts | Three undocumented formats that change on minor releases, contributing nothing to any PASS or FAIL. They would only colour nodes |
| Zero models in verification | Small local models running the checks | 10,000 parameters cannot hold a token embedding table; a 32k vocabulary at `d_model=8` costs 256,000 parameters before a single layer. The correct answer is no model, not a small one |
| Deterministic static analysis plus execution proof | An LLM reading both sides and judging | The extraction step is where the difficulty lives, and a model judging its own reading is unauditable |
| A plain loop with a stopping condition | A manager agent orchestrating the cycle | It is roughly thirty lines. An LLM adds nondeterminism and removes the ratchet guarantee |
| Producer is authoritative per seam | Letting both agents fix toward each other | Otherwise A changes to match B while B changes to match A, and the round produces a fresh mismatch |
| Baseline anchored to merge-base | Baseline anchored to session start | If agents were already working when Irus starts, the mismatch lands in the baseline and becomes permanently invisible |
| Full receipt re-run with a monotonic ratchet | Re-checking only the seam just fixed | A fix in round two can break a seam that passed in round one, and the loop would report progress while getting worse |
| **REVERSED 9 Aug 2026.** Guests read and edit the host's files, behind an opt-in and a token | Originally: rejected in favour of event-only sync, on the grounds that Live Share solved host-keeps-the-files in 2017 | The original call narrowed the owner's stated intent, which was always that a guest works on the host's project. The security concerns were real and are handled with guards rather than by removing the feature: off unless the host passes `--share-files`, which itself refuses to start without a token; a token on every call including reads; paths validated on the resolved path so `..`, absolute paths and outward symlinks are all caught by one check; `.env`, credentials, `node_modules` and `.git` never served; writes size capped. See `irus/fileshare.py` and the eleven guard tests in `tests/test_mcp_conformance.py` |
| No published benchmark | SeamBench as a citable corpus | Circular while our checker defines the label; the name also collides with an existing `seam-benchmark` organisation. Execution proof fixes the circularity, third-party labelling is still needed, and that is not a two-week item |
| Drop migration checks | Detecting migrations never applied | Fully commodity: `prisma migrate status`, `django migrate --check`, `flyway info`, `rails db:migrate:status` all ship it |
| Drop unused-export detection | Competing with knip | knip owns it; ts-prune, depcheck, and unimported are all archived and point at it |
| Named Irus | Keeping the earlier working name, or a name describing a joint | Renamed on Aug 9 2026, owner's call. The earlier name described passing work between people, which is the coordination product that was cut, so it argued for the wrong thing |
| Keep the full surface for the demo | Cutting to one product, as advised | Owner's call, made deliberately on Aug 9 2026 for a hackathon context. Agreed shape: broad on the surface, narrow underneath, with exactly one path working under the lights |
