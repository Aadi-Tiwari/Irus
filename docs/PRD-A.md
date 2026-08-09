# Irus PRD, Part A: Problem, Users, and Product Definition

Part B covers requirements, measurement, delivery, and the decision log.
`SPEC.md` holds the technical design. `BUILD-PLAN.md` holds the schedule.

Status: draft, Aug 9 2026. Two gates unresolved (see Part B, section 8).

---

## 1. Summary

Irus catches the bug that happens between two AI coding agents.

When two agents each build one half of a feature, both finish, both report
success truthfully, and both halves compile. The disagreement between them belongs
to nobody, survives code review, and merges clean. Irus finds that disagreement
before the merge, proves it by executing it, and renders it on a live map.

**One line for a judge:** "When two AI agents build two halves of a feature,
integration accuracy drops from 58% to 25%. Both agents report success. Nothing
catches it."

---

## 2. The problem

### 2.1 What actually happens

An agent working in worktree A is told to build the checkout endpoint. It writes
`POST /api/checkout` accepting a Pydantic model with `email` and `amount`. It runs
its tests, they pass, it reports done. Truthfully.

An agent working in worktree B is told to build the checkout form. It writes a
`FormData` submission with fields `user_email` and `total`. It runs its tests, they
pass, it reports done. Truthfully.

Neither agent is wrong about its own half. Neither agent ever saw the other half.
Git merges both branches without a conflict, because they touched different files.
The typechecker validates each side alone and finds nothing. CI runs each branch
against base, never against each other. The application is broken and every signal
available says it is fine.

### 2.2 Why existing signals miss it

| Signal | Why it misses |
|---|---|
| Git merge | Adjudicates the file tree, not intent. Different files, no conflict. |
| Typecheckers | Verify each side in isolation. Both sides are internally consistent. |
| Per-branch CI | Tests each branch against base, never against the other branch. |
| Per-worktree tests | Agent A's green suite describes a state that never contained agent B's changes. |
| Code review | The reviewer sees one PR at a time, and the halves look correct individually. |
| Agent self-report | The agent reports on its own half, accurately. |

The merged state where the bug lives is never built and never tested by anything.

### 2.3 Evidence that this is real

Third-party measurements, not our claims:

| Finding | Source |
|---|---|
| Integration accuracy falls 58% to 25% as spec detail is stripped between two agents | *The Specification Gap*, arXiv 2603.24284 |
| 27.67% merge-conflict rate across 142,000+ agentic PRs in 59,000+ repos | *AgenticFlict*, arXiv 2604.03551 |
| GPT-5.5 at 55.4% loose, 28.6% under strict OpenAPI contract testing | *BackendForge*, arXiv 2607.11042 |
| No open model above 40% on web API integration | *WAPIIBench*, arXiv 2509.20172 |
| Six 2026 coordination papers, each with its own private ad-hoc evaluation | STORM, CAID, Co-Coder, Claim Plane, ATM, grite |

**Honest caveat, stated in the pitch and not buried:** the 27.67% figure counts
merge conflicts, which git already surfaces. Irus targets the class git merges
clean. The 58%-to-25% number is the on-target one and is the one we lead with.

---

## 3. Who this is for

**Primary user: a developer running more than one coding agent at once**, whether
that is four agents across git worktrees on one machine or two people on one
machine each driving their own agent.

This population is small today and growing. We state that plainly rather than
pretending otherwise. Every vendor now ships parallel agents (Cursor runs 8,
Claude Code has agent teams, Codex has cloud runs), so the population is defined
by a shipped feature rather than by a habit we hope people adopt.

**Secondary user: anyone merging agent-written branches.** `irus check` runs as a
merge gate or CI step and requires no live session, no watching, and no adoption
by anyone else on the team. One person can add it to a repo and get value alone.

**Explicitly not a user:** an engineering manager wanting visibility into what
their team is doing. That product was considered and rejected. See Part B,
section 10.

---

## 4. Why now

Three things became true at once.

1. **Parallel agents shipped.** Running one agent was the norm eighteen months
   ago; running several is a first-class feature in every major tool now.
2. **Commit and PR volume stopped meaning anything.** One prompt writes 500 lines,
   or an agent loops for an hour and commits nothing.
3. **Nobody built the check.** Verified across roughly 40 tools in August 2026:
   every tool that catches an interface mismatch requires a spec, hand-written
   contract tests, or live traffic. Every tool that manages parallel agents stops
   at isolate-and-hand-to-human. Not one verifies that the outputs are mutually
   consistent.

---

## 5. What Irus is

A local, offline command-line tool plus a live local page.

1. **It reads both sides of a boundary** and compares what each one declares.
   Deterministic, no model, milliseconds, identical answer every time.
2. **It proves the disagreement by executing it**, through the framework's own
   test client inside a transaction that rolls back. The app decides, not Irus.
3. **It reports only what this session introduced**, by baselining against the git
   merge-base. A repo's pre-existing weirdness is invisible.
4. **It shows the result as a map** where healthy code is dim and colourless, and
   the connection that should exist but does not is drawn explicitly as a dashed
   red arc between the two nodes that should have been wired together.

### 5.1 The two-stage shape, and why both exist

Stage 1 **detects** without running anything: fast, offline, works when the app
cannot boot mid-build. Stage 2 **proves** by running: slower, definitive, and its
verdict comes from reality rather than from our checker.

They are not competing methods. Detection narrows the search; proof settles it.
A finding that survives both is not an opinion.

### 5.2 What makes the map worth having

In a normal dependency graph the interesting thing is the edges that exist. Here
the interesting thing is the edge that should exist and does not, and absence is
invisible by default. Drawing that absence explicitly is the product. Everything
else on screen is context for it.

---

## 6. Jobs to be done

| Job | Today | With Irus |
|---|---|---|
| "Did the two halves my agents built actually connect?" | Run the app and click through it, or find out in review | One command, answer in milliseconds |
| "My agents both said done. Is that true?" | No way to check | A receipt: pass or fail per claim, checked against the filesystem |
| "Is there code here that connects to nothing?" | Partly covered by knip for exports, nothing for endpoints or env vars | Orphan and env-var findings, session-scoped |
| "Which env var will blow up in production?" | Find out in production | Cross-referenced against `.env`, compose, and CI config |
| "What are my agents doing right now?" | Watch several terminals | One map |

---

## 7. Functional requirements

Priority: **P0** must ship, **P1** ships if time allows, **P2** deferred.

### Detection

| ID | Requirement | Priority |
|---|---|---|
| A-R1 | Extract route path, method, and request payload shape from the producer side (FastAPI) | P0 |
| A-R2 | Extract request target, method, and body construction from the consumer side (React fetch, including literal objects, `JSON.stringify`, and `FormData`) | P0 |
| A-R3 | Compare the two and emit a finding naming both file paths and the exact disagreement | P0 |
| A-R4 | Detect env vars read in source but set nowhere (`.env`, `.env.example`, `docker-compose.yml`, `vercel.json`, GitHub Actions `env:` and `secrets:`) | P0 |
| A-R5 | Compare response payload shape as well as request | P1 |
| A-R6 | Detect zero-caller endpoints and unmounted components | P1 |
| A-R7 | Support a second stack pair | P2 |

### Proof

| ID | Requirement | Priority |
|---|---|---|
| A-R8 | Tier 1: construct the request and validate it against the declared schema without sending it | P0 |
| A-R9 | Tier 2: send through the framework's own test client inside a transaction that rolls back | P0 |
| A-R10 | Refuse to send any request to a non-localhost host | P0 |
| A-R11 | Never issue a real POST, PUT, PATCH, or DELETE over the network; those go through the test client or not at all | P0 |
| A-R12 | Tier 3: real HTTP for GET, HEAD, and OPTIONS only | P2 |

### Scoping

| ID | Requirement | Priority |
|---|---|---|
| A-R13 | Compute the baseline against the git merge-base of the active branches, in a temporary worktree, cached by SHA | P0 |
| A-R14 | Suppress every finding present in the baseline; report only what this session introduced | P0 |
| A-R15 | Fall back to `HEAD` as the anchor when there is a single tree with uncommitted work | P0 |

### Output

| ID | Requirement | Priority |
|---|---|---|
| A-R16 | Render findings as pass/fail receipt lines readable in a terminal with no UI | P0 |
| A-R17 | `irus check` exits nonzero when a high-confidence finding exists, so it works as a merge gate and CI step | P0 |
| A-R18 | Append every event to a JSONL log that can be replayed to reconstruct identical state | P0 |
| A-R19 | `irus watch` serves a live local page over SSE, self-contained, offline, no build step | P1 |
| A-R20 | The page draws baseline as dim context and this session at full colour, with missing connections as dashed red arcs | P1 |
| A-R21 | Confidence tiers, where only high-confidence findings fail the gate | P1 |
| A-R22 | MCP surface exposing `status`, `next`, `claim`, `release` as text for agents | P2 |

### Coordination

| ID | Requirement | Priority |
|---|---|---|
| A-R23 | Declare the producer authoritative per seam by default, overridable in config, recorded in the receipt | P1 |
| A-R24 | Assign each failing seam to exactly one owner per round | P1 |
| A-R25 | Fix loop with a monotonic ratchet: a round is accepted only if total failures strictly decrease | P1 |

---

## 8. Non-goals

Each of these was considered and rejected on the record. Reasons are in Part B,
section 10, so they stay rejected.

- A manager-visibility or team-status product
- Agent session-transcript parsing
- Detecting migrations that were never applied
- Unused export and file detection
- An LLM acting as the manager, the judge, or any part of the verification path
- A file-sync, tunnel, or remote-execution protocol
- A published benchmark program
- Small language models anywhere in the system

---

## 9. Competitive position

The wedge is: **a zero-setup, spec-free, cross-language check that the producer and
the consumer agree, run against the union of unmerged branches, before merge.**

| Category | Example | Why it does not cover the wedge |
|---|---|---|
| Contract testing | Pact | Needs hand-written consumer tests, provider verification, a broker, and CI changes on both sides |
| Spec diffing | oasdiff, openapi-diff | Compares spec to spec, never reads code. No spec change means no finding |
| Spec-driven fuzzing | Schemathesis, RESTler | Generates requests from the spec, so it sends what the server expects and passes |
| Typed clients | tRPC, ts-rest | TypeScript on both ends only, and a raw `fetch()` bypasses it entirely |
| Dead-code tools | knip | Route files are registered as entry points on purpose, so endpoints can never be flagged |
| Agent orchestrators | Conductor, claude-squad, emdash, Cursor, Claude Code agent teams | Isolate and hand to a human. None builds or tests the merged state |
| Graph partitioners | roam-code | Prevents collisions up front, never checks whether agents complied |
| Merge queues | Bernstein | Runs the tests that exist. The missing tests are exactly what the agents did not write |

**Market risk we state rather than hide:** this category has a high death rate.
Vibe Kanban is sunsetting at 27,700 stars for lack of a business model, Crystal is
deprecated, Terragon is dead, uzi abandoned, container-use dormant, humanlayer
deprecated by its own maintainer. That is a signal about monetisation, and it does
not change whether the check is useful.

---

## 10. Success criteria

**For the demo:**

1. The problem is established in the first spoken sentence, with a third-party
   number, before any architecture is mentioned.
2. A real mismatch, from a recorded real session and never planted, appears on
   screen and is legible from three metres.
3. Detection latency and an honest findings count on real public repositories are
   both stated out loud.
4. Everything runs with the wifi off.

**For the product:**

1. A developer who runs one command on a repo they did not write gets fewer than
   three false positives on the same screen as at least one true finding.
2. `irus check` can be added to a repo by one person and produce value with no
   one else adopting anything.
3. Every published number has its false positives published alongside it.
