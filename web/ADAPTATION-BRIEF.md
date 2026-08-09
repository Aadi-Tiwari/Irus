# Irus site: adaptation brief

This site is the Mycelium landing page, reused as a template. **The visual system is
frozen.** Every worker on this site follows the same two rules:

1. **Do not change the UI.** Keep the layout, the Tailwind classes, the colors, the
   emerald accent, the backdrop, the grain, the spores, the masks, the scroll-snap,
   every `motion` animation, every timing, every easing curve, every transition, every
   canvas/SVG drawing routine and its geometry. If a component draws a network of nodes
   with pulsing edges, it still draws a network of nodes with pulsing edges.
2. **Change everything else to Irus.** All copy, all headings, all labels, all data,
   all fixture arrays, all node names, all terminal transcripts, all variable and type
   names that carry Mycelium's vocabulary. Nothing on the page should mention skills,
   trails, spores-as-knowledge, the commons, token savings, or a shared agent memory.

Where a Mycelium concept has no Irus counterpart, replace it with the Irus concept
occupying the same slot in the argument, not with filler. Where the array lengths differ
(five MCP tools becomes four), keep the grid working; do not pad with invented items.

---

## What Irus is

**Irus catches the bug that happens between two AI coding agents.**

Agent A builds the checkout endpoint. It expects JSON with `email` and `amount`. Its
tests pass. It reports done, truthfully. Agent B builds the checkout form. It posts
`FormData` with `user_email` and `total`. Its tests pass. It reports done, truthfully.

Neither agent is wrong about its own half. Neither ever saw the other half. Git merges
both branches without a conflict because they touched different files. The typechecker
validates each side alone and finds nothing. CI runs each branch against base, never
against the other branch. The application is broken and every signal available says it
is fine.

Irus finds that gap before the merge, proves it by running it, and shows it on a live map.

The canonical terminal output, used verbatim wherever a transcript is needed:

```
$ irus check
POST /api/checkout
  endpoint exists        PASS
  route mounted          PASS
  client calls it        PASS
  encoding matches       FAIL   client sends multipart, server expects json
  payload shape matches  FAIL   server requires `amount` (int); server requires `email` (str)

5 finding(s) introduced this session (3 high) | baseline acab5370f983 suppressed 1 pre-existing
$ echo $?
1
```

## Vocabulary map (Mycelium -> Irus)

| Mycelium | Irus |
|---|---|
| skill | **seam** (a boundary where one side produces and the other consumes) |
| skill synthesis / distilling a session | **the seam check** (static analysis of both sides) |
| trail / stigmergy / paths strengthening | **the round loop and its ratchet** |
| trust score (Bayesian pass rate) | **confidence tier** (high / medium / unknown) |
| the commons / shared network | **the live map** (`irus watch`) and the findings ledger |
| tokens / energy / water / CO2 saved | **sweep latency, findings introduced this session, tests passing** |
| reuse event | **finding**, or a **round** of the loop |
| poisoned skill / prompt injection | **execution safety: proof cannot escape localhost** |
| self-healing skill | **the fix loop with a monotonic gate** |
| MCP search / apply / report tools | **MCP `status`, `next`, `claim`, `release`** |
| forest / roots / mycelium network | keep the imagery as pure visual texture; never name it in copy |

## Numbers that are true and may be used

Only these. Do not invent any others, do not round them up, do not imply anything is
measured that is not.

- Full sweep, 500 source files: **0.28s best, 0.51s median** (budget 2.0s)
- Incremental re-check after one edit: **83ms best, 105ms median** (budget 200ms)
- **96 tests pass**
- Engine has **no required dependencies**; standard library only, runs offline
- Third-party: integration accuracy falls **58% to 25%** as spec detail is stripped
  between two agents (*The Specification Gap*, arXiv 2603.24284)
- Third-party: **27.67%** merge-conflict rate across 142,000+ agentic PRs
  (*AgenticFlict*, arXiv 2604.03551) — if used, say plainly that git already surfaces
  merge conflicts and Irus targets the class git merges clean
- Third-party: GPT-5.5 scores **55.4% loose, 28.6% strict** under OpenAPI contract
  testing (*BackendForge*, arXiv 2607.11042)
- Third-party: **no open model above 40%** on web API integration (*WAPIIBench*, arXiv 2509.20172)

**Honestly unverified, and the site says so out loud where the Mycelium original showed
live commons totals:** Irus has not been run against a repository the author did not
write, so the real-world false-positive rate is unmeasured. `irus ledger` exists to fill
that in and it is not filled in yet. Never show a fabricated accuracy, precision, recall,
adoption, star, or user number anywhere on this site.

## The argument, in the order the page makes it

1. **Hero** — Irus, one line, four stat bubbles.
2. **Problem** — two agents, two halves, both truthfully report success, git merges
   clean, every signal says fine, app is broken.
3. **What it is** — a zero-setup, spec-free, cross-language check that agent A's
   producer and agent B's consumer actually agree, run against the union of unmerged
   branches, before merge.
4. **Features 01-06** (see below).
5. **Install / compare** — `pip install -e .` and one command, against the setup a
   contract-testing stack demands.
6. **Dashboard** — the live map and the honest ledger.

## The six features, in order

**01 - custom section (was SkillSynthesisSection): "Two diffs in. One finding out."**
Stage 1 static seam check. Python parsed with the standard library `ast`; TypeScript with
a dependency-free scanner that masks strings and comments before any structural parsing,
so a brace inside a string cannot fool it. It reads both sides and compares what each
declares. No model anywhere in the verification path. Same code in, same answer out,
every time. Seam kinds in priority order: HTTP route path/method/request payload shape;
response payload shape; env var read but never set; zero-caller endpoint or unmounted
component.

**02 - custom section (was McpToolsSection): "The surface agents actually use."**
Agents read the map as compact text, not a picture. Four MCP tools: `status` (current
failing seams and orphans), `next` (an unclaimed piece of work), `claim` and `release`
(advisory coordination). The graph is for humans, the text is for machines. The CLI
surface belongs here too if the layout wants more cells: `irus check`, `irus watch`,
`irus baseline`, `irus suppress`, `irus ledger`.

**03 - custom section (was TrailsSection): "A loop that cannot go backwards."**
snapshot baseline -> detect -> prove -> report -> dispatch one owner per failing seam ->
re-run the full receipt set -> accept the round only if total failing seams strictly
decreased. A round that does not strictly reduce failures is reverted. The loop cannot
report progress while getting worse. Per-seam results are cached against a content hash
of both sides, so a re-run only recomputes seams whose code actually changed. The manager
is a plain loop with a stopping condition, not an agent.

**04 - generic feature (was EarnedTrustViz): "Unknown is never high confidence."**
Only high-confidence findings fail the merge gate. A body assembled through a helper the
scanner cannot follow is reported as unknown, because that is our limitation rather than
the code's defect. A spread (`...rest`) suppresses missing-field checks for that seam
instead of guessing. Irus never claims zero false positives; `irus ledger` runs unfiltered
and publishes every finding for hand labelling, including the wrong ones.

**05 - custom section (was ProvenHealingSection): "It proves it by running it."**
Stage 2 execution proof, three tiers, cheapest first. (1) Build the request without
sending it and validate against the handler's declared schema: microseconds, zero side
effects, catches JSON-versus-multipart exactly. (2) Send through the framework's own test
client (FastAPI `TestClient`, Django test client, supertest) inside a transaction that
rolls back: in-process, no network, no real rows. This is the default. (3) Real HTTP for
GET, HEAD, OPTIONS only. The verdict comes from the application, not from our checker,
which is what makes it evidence. Then the authority rule: by default the producer is
authoritative and the consumer adapts, it is overridable per seam, and the decision is
written into the receipt so a later round cannot flip it, which makes fix-loop
oscillation structurally impossible rather than merely unlikely.

**06 - generic feature (was AntiPoisonViz): "Proof that cannot escape."**
Execution is opt-in. Nothing is sent off localhost. No mutating method ever travels over
the wire. The local store is fingerprinted before and after every proof run and a change
aborts loudly rather than being reported as a pass. A model may write a test; a model
never decides whether a test passed. Nothing leaves your machine: no network, no
telemetry, no accounts.

## The baseline, which appears in several places

The baseline is anchored to the git merge-base of the active worktrees, never to
wall-clock time. Anchoring to "when the tool started" would hide the bug whenever agents
were already working before the tool was launched, which is the common case and the exact
failure the tool exists to catch. Everything already in the baseline is invisible; Irus
reports only what this session introduced. Two people computing a baseline get identical
results, and the demo replays identically every run because the anchor is a commit rather
than a moment.

## The live map, which the visualizations depict

Two layers on one canvas. Baseline layer: small, dim, thin edges, no labels, pure
context. Session layer: full size, color, labels, on top. The screen is dense and alive
and the eye goes straight to the three bright things because everything else is
deliberately recessive.

Status colors, if a component needs semantic color (otherwise keep the template's
emerald):

| State | Hex |
|---|---|
| Broken seam | `#d03b3b` |
| Orphan | `#c98500` |
| Active now | `#3987e5` |
| Healthy | `#898781` |

Healthy nodes carry no color. Color is scarce and always means "look here." Absence is
drawn explicitly: a connection that should exist and does not is a dashed red arc between
the two nodes with the endpoints pulled slightly apart so the gap is legible. Node size is
blast radius. Layout is seeded deterministically from node id so the codebase looks the
same every session and spatial memory works. Identity, meaning which agent, is a ring or a
filter, never the fill.

## Positioning, for the compare section

- **Contract testing (Pact)** catches this bug but needs hand-written consumer tests per
  interaction, provider verification wired into both suites, a broker, and CI changes on
  both sides.
- **Spec diffing (oasdiff, openapi-diff)** compares spec to spec and never reads code. If
  the spec always said JSON and the frontend always posted multipart there is no diff.
- **Spec-driven fuzzing (Schemathesis, RESTler)** generates requests from the spec, so it
  sends JSON, the server accepts, the test passes, and the frontend is still broken.
- **Typed clients (tRPC, ts-rest, codegen)** prevent the bug by construction but only for
  TypeScript on both ends, and a hand-written `fetch()` bypasses all of it.
- **Agent orchestrators** isolate agents into worktrees and hand results to a human. Not
  one verifies that the outputs are mutually consistent.

## Writing rules

- **Never use an em dash.** Restructure the sentence instead.
- Plain declarative sentences. No marketing superlatives, no "revolutionary", no
  "seamlessly", no exclamation marks.
- Never state a capability Irus does not have, and never imply a measurement that has not
  been taken.
- Comments in code state constraints, not narration. Keep the existing comment density.

## Repo facts

- Package name: `irus`. GitHub link target: `https://github.com/Aadi-Tiwari/irus`.
- Install: `pip install -e .`; extras `".[config]"` (PyYAML) and `".[prove]"`
  (starlette + httpx).
- No Supabase, no `@mycelium/shared`, no embeddings. The live-data layer becomes a local
  deterministic replay of an append-only event log, which is what `irus watch` actually
  does, so the dashboard keeps its motion with no backend.
