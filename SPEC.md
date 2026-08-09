# Irus

**Irus catches the bug that happens between two AI agents.**

When two agents build two halves of a feature, each one finishes its own half and
truthfully reports success. The gap between the halves belongs to nobody. Agent A
ships an endpoint that expects JSON. Agent B's form posts multipart. Both compile.
Both agents report done. Git merges clean. Nothing catches it until a human clicks
the button.

Irus finds that gap before the merge, proves it by running it, and shows it on a
live map.

---

## 1. Why this problem is real

Third-party measurements, not our own claims:

| Finding | Source |
|---|---|
| Integration accuracy falls from 58% to 25% as spec detail is stripped between two agents | *The Specification Gap*, arXiv 2603.24284 |
| 27.67% merge-conflict rate across 142,000+ agentic PRs in 59,000+ repos | *AgenticFlict*, arXiv 2604.03551 |
| GPT-5.5 scores 55.4% loose but 28.6% under strict OpenAPI contract testing | *BackendForge*, arXiv 2607.11042 |
| No open model above 40% on web API integration | *WAPIIBench*, arXiv 2509.20172 |

Caveat we state honestly: the 27.67% figure counts merge conflicts, which git
already surfaces. Irus targets the class git merges clean. The 58%-to-25% number
is the on-target one and is the one used in the pitch.

---

## 2. What nobody else does

Verified against ~40 tools, August 2026.

- **Contract testing (Pact)** catches this bug but needs hand-written consumer
  tests per interaction, provider verification wired into both suites, a broker,
  and CI changes on both sides. Zero-config on an existing repo: no.
- **Spec diffing (oasdiff, openapi-diff, openapi-changes)** compares spec to spec
  and never reads code. If the spec always said JSON and the frontend always
  posted multipart, there is no diff and no finding. Structurally incapable.
- **Spec-driven fuzzing (Schemathesis, RESTler)** generates requests *from* the
  spec, so it sends JSON, the server accepts, the test passes, and the frontend
  is still broken. Dredd is archived.
- **Typed clients (tRPC, ts-rest, codegen)** prevent the bug by construction, but
  only for TypeScript on both ends, and a hand-written `fetch()` bypasses all of
  it. `Body.json()` returns `Promise<any>` and `RequestInit.body` is `BodyInit |
  null`, so a raw fetch is untypeable. That is precisely the hole an agent falls
  through.
- **Agent orchestrators (Conductor, claude-squad, emdash, agent-orchestrator,
  Cursor, Codex cloud, Claude Code agent teams)** isolate agents into worktrees
  and hand results to a human. Not one verifies that the outputs are mutually
  consistent. Where docs say "verification" it is per-worktree tests, per-PR CI
  against base, one agent critiquing another, or best-of-N selection. None of
  those ever builds the merged state where the bug lives.
- **Dead-code tools (knip)** own unused exports and files. They cannot flag
  zero-caller endpoints, because framework plugins register route files as entry
  points on purpose.

**The unoccupied wedge:** a zero-setup, spec-free, cross-language check that agent
A's producer and agent B's consumer actually agree, run against the union of
unmerged branches, before merge.

### Direct competitors to position against

| Tool | What it does | Our difference |
|---|---|---|
| **roam-code** (506★, very active) | Partitions a symbol graph into non-overlapping agent zones and emits per-agent contracts | Prevents by partitioning; never checks whether agents obeyed. Irus verifies after. |
| **Bernstein** (818★) | Cherry-picks each agent branch onto main, runs lint and tests | Needs tests to already exist. Irus works when the missing tests are exactly what the agents did not write. |
| **git-regress** (2★) | Tree-sitter symbol footprints across PRs | Idea is thinkable and nobody adopted it. Worth knowing it exists. |

---

## 3. Architecture

### 3.1 Baseline (anchored to a commit, never to wall-clock time)

The baseline is the set of findings that already existed before this session. It
is computed once against the **git merge-base** of the active branches, in a
temporary worktree:

```
git worktree add /tmp/irus-base $(git merge-base <branchA> <branchB> ...)
```

Results are cached keyed by that SHA. With a single tree and uncommitted work,
anchor to `HEAD` and treat everything uncommitted as this session.

Consequences: two people computing a baseline get identical results, and the demo
replays identically every run because the anchor is a commit rather than a moment.

**Everything already in the baseline is invisible.** Irus reports only findings
this session introduced. This one decision fixes the false-positive flood, the
hairball graph, and the demo paradox at once.

### 3.2 Capture (filesystem and git, not transcripts)

Irus learns what each agent did from `git diff` per worktree plus file mtimes.

Agent session-transcript parsing is **explicitly out**. Three undocumented formats
that change on minor releases, contributing nothing to any PASS or FAIL, is
unacceptable risk for a two-week build.

### 3.3 Stage 1: static seam check (detection)

Deterministic static analysis comparing declared interfaces on both sides of a
boundary. No model anywhere in this path. Same code in, same answer out, every
time. Runs offline in milliseconds.

Seam kinds, in build priority order:

1. HTTP route: path, method, and request payload shape
2. Response payload shape
3. Env var read but never set
4. Zero-caller endpoint / unmounted component

### 3.4 Stage 2: execution proof (confirmation)

Suspicious seams from stage 1 get proven by running them. Three tiers, cheapest
first:

1. **Build the request without sending it** and validate against the handler's
   declared schema. Microseconds, zero side effects. Catches JSON-versus-multipart
   exactly.
2. **Send through the framework's own test client** (FastAPI `TestClient`, Django
   test client, supertest) inside a transaction that rolls back. In-process, no
   network, no real rows, no emails, no payment sandbox. This is the default.
3. **Real HTTP only for GET, HEAD, OPTIONS.** Never a real POST, PUT, or DELETE.
   Refuse to run against any base URL that is not localhost.

**Hard rule: a model may write the test. A model may never decide whether the test
passed.** Model authors, machine judges. This preserves "no model in the
verification path" while using a model where it is genuinely good.

### 3.5 Receipts

Every agent completion claim becomes filesystem-checked pass/fail lines:

```
POST /api/checkout
  endpoint exists                PASS
  route mounted on app           PASS
  client calls it                PASS
  payload shape matches          FAIL   form sends multipart, handler expects JSON
  proven by execution            FAIL   422 Unprocessable Entity
  covered by a test              FAIL   no test references this route
```

Receipts are written to an append-only JSONL log and are also committable, so
`irus check` works as a merge gate and a CI step for repos that never run the
live page.

### 3.6 Authority rule (which side is wrong)

Irus cannot infer who should change. So it declares:

- **Default: the producer is authoritative.** The side that defines the interface
  wins; the consumer adapts.
- Overridable per seam in config.
- The decision is written into the receipt so a later round cannot flip it.
- Each failing seam is assigned to exactly one agent per round.

This makes fix-loop oscillation structurally impossible rather than merely
unlikely.

### 3.7 The loop (a plain loop, not an agent)

```
snapshot baseline
repeat:
    detect  (stage 1, full sweep)
    prove   (stage 2, on stage-1 hits only)
    report  (receipts + graph)
    dispatch one owner per failing seam
    re-run FULL receipt set
    accept the round only if total failing seams strictly decreased
until nothing new, or the ratchet refuses a round, or the round limit is hit
```

Per-seam results are cached against a content hash of both sides, so a full re-run
only recomputes seams whose code actually changed.

The monotonic gate is the important part: a round that does not strictly reduce
failures is reverted. The loop cannot report progress while getting worse.

### 3.8 The live page

`irus watch` starts a local HTTP server, opens a browser, and streams over
server-sent events from the append-only JSONL log. One self-contained HTML file,
no build step, no CDN, works offline. On connect the server replays the whole log,
so a refresh rebuilds identical state and the log doubles as a recording.

**Two layers on one canvas:**

- **Baseline layer:** small, dim, thin edges, no labels. Pure context.
- **Session layer:** full size, color, labels, on top.

The screen looks dense and alive; the eye goes straight to the three bright
things, because everything else is deliberately recessive.

**Color** (status encoding, validated all-pairs for colorblindness in both themes):

| State | Dark | Light |
|---|---|---|
| Broken seam | `#d03b3b` | `#d03b3b` |
| Orphan | `#c98500` | `#eda100` |
| Active now | `#3987e5` | `#2a78d6` |
| Healthy | `#898781` | `#898781` |

Healthy nodes carry no color. Color is scarce and always means "look here."
Worst pair in dark mode: ΔE 10.2 deutan, 16.9 normal vision. Light-mode amber sits
below 3:1 contrast, so it carries a visible label.

**Absence is drawn explicitly.** A connection that should exist and does not is a
dashed red arc between the two nodes, with the endpoints pulled slightly apart so
the gap is legible. That single mark is the product; everything else is context.

Node size is blast radius. Layout is seeded deterministically from node id so the
codebase looks the same every session and spatial memory works.

Identity (which agent) is a ring or a filter, never the fill.

### 3.9 MCP surface

Agents read the map as compact **text**, not a picture, and call:

- `status`: current failing seams and orphans
- `next`: an unclaimed piece of work
- `claim` / `release`: advisory coordination

The graph is for humans. The text is for machines.

### 3.10 Multiplayer by not building it

A guest joins the host's machine via SSH, tmux, or VS Code Live Share and runs
their own agent with their own credentials, so they pay for their own usage and
no files move. Irus builds neither the connection nor the permission system; the
coding agents' existing permission settings gate execution. Everything then runs
on one filesystem, so Irus needs zero networking.

Corrections that matter here: Claude Code Remote Control is single-account by
design and grants no one else access, contrary to several blog posts. The
host-machine-sharing category is contracting (JetBrains sunsetting Code With Me,
CoScreen shut down July 2026), so do not build into it.

Optional later: `irus watch --share` relays only the append-only event log, which
is kilobytes. Seam verification needs the *interface*, not the implementation, so
cross-machine checking works without any file sync.

---

## 4. Honesty rules

1. **Never claim zero false positives.** Commit a findings ledger: full unfiltered
   output on five real public repos, every finding hand-labeled true or false,
   totals stated plainly. "Eleven findings, three true" cannot be ambushed.
2. **Confidence tiers.** Only high-confidence findings fail the merge gate.
3. **A model may write a test; a model may never judge one.**
4. **Never plant a bug and present it as found.** Demo failures come from a
   recorded real session.

---

## 5. Explicitly out of scope

| Cut | Why |
|---|---|
| Agent session-transcript parsing | Three undocumented formats, changes on minor releases, contributes nothing to any PASS/FAIL |
| Migrations never applied | Fully commodity: `prisma migrate status`, `django migrate --check`, `flyway info`, `rails db:migrate:status` all ship it |
| Unused exports and files | knip owns this; ts-prune, depcheck, unimported all archived |
| Manager as an LLM agent | It is a loop with a stopping condition, roughly thirty lines |
| A public benchmark program | Circular if our checker defines the label, and the name collides with an existing `seam-benchmark` org. Execution-proof labels fix the circularity; third-party labeling is still needed and is not a two-week item |
| File-sync or tunnel protocol | Live Share solved it in 2017; that category is contracting |
| Tiny language models | 10k parameters cannot hold a token embedding table; the right answer is zero models, not small ones |

---

## 6. Demo (90 seconds)

1. **Problem, one sentence, no team intro.** "When two AI agents build two halves
   of a feature, integration accuracy drops from 58% to 25%. Both agents report
   success. Nothing catches it."
2. **Run it live.** Replay the recorded session fixture. Canvas is dim context.
   Two agents finish. One dashed red arc appears.
3. **Show the number.** Detection latency, findings count on five public repos with
   the true/false split published, running offline on this laptop.
4. **The twist.** "There is no model anywhere in this. It found it in forty
   milliseconds without running anything." Then press one key and stage 2 executes
   and confirms it. Detection and proof, not two competing methods.
5. **What's next.** The env-var check is the only verified-open gap in this space;
   name what it generalizes to.

**Never demo a live agent.** Slow, nondeterministic, and it will not produce the
bug on cue. Replay the fixture.

**Known stage risks:** file watchers storming on `node_modules`, SSE dropping when
the laptop sleeps, an empty canvas, a hairball canvas.

---

## 7. Open and unverified

- Whether mid-build worktrees can actually be booted. This is the load-bearing
  premise: if the app runs, one request kills the headline example and static
  analysis is merely convenient rather than necessary. **Untested.**
- Whether three real mismatches can be reproduced from our own history. **Untested.**
- Cross-language payload shape matching cost. The canonical paper (Wittern et al.,
  ICSE 2017) reported 96% precision on endpoint and method, 87.9% on payload, and
  was never productized in nine years. That is either the opportunity or the
  warning, and current evidence cannot distinguish them.
- Whether the category can sustain anything: Vibe Kanban is sunsetting at 27,700
  stars for lack of a business model, Crystal is deprecated, Terragon is dead, uzi
  abandoned, container-use dormant, humanlayer deprecated by its own maintainer.
