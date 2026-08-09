# Irus build plan

Fourteen days, solo. Read `SPEC.md` first.

**Four days are locked and non-negotiable: days 1-2 at the front, days 13-14 at
the end. The other ten are negotiable and features get cut from the bottom of the
priority list when time runs out.** Discovering on day twelve that there is no
rehearsal time is the single most common way this fails.

---

## Stack decisions (already made, do not relitigate)

| Decision | Choice | Reason |
|---|---|---|
| Irus's own language | Python 3.11+ | `ast` built in, fastest to write, no build step |
| Parsing both sides | tree-sitter (`tree-sitter-python`, `tree-sitter-typescript`) | One library covers both languages; no Node dependency in the core |
| Target stack pair for v1 | FastAPI + React/fetch | Most common agent-built pair; matches the headline example |
| Event log | Append-only JSONL, one line per event | Replayable, diffable, doubles as the demo recording |
| Web server | Python `http.server` + SSE | Zero dependencies, no websocket handshake to debug |
| Page | One self-contained HTML file | No build step, no CDN, works offline |

Upgrade path noted but not built: if TypeScript type resolution becomes the
blocker on payload shapes, swap the TS side to `ts-morph` in a Node subprocess.
Do not start there.

---

## Days 1-2 (LOCKED): the fixture and the two gates

This is the only work that can kill the project, so it happens first.

**Build the fixture.** Take a small real full-stack project. Run agents on it in
parallel worktrees while recording every filesystem event to a JSONL file. That
recording becomes the demo replay, the test fixture, and the first labeled
samples, all from one activity.

**Gate A: do mid-build worktrees boot?** Try to start the app in each worktree
mid-session.
- If they **do not** boot, the static-analysis premise holds. Proceed as specced.
- If they **do** boot, stage 2 is the real product and stage 1 is an optimisation.
  Rewrite the pitch accordingly and reverse their priority in the build order.
  This is not a failure, it is a cheaper product.

**Gate B: can three real mismatches be reproduced?** From the recorded session or
from prior history, find three genuine cases where two agents produced
incompatible sides and both reported success.
- Three or more: proceed.
- One or two: proceed with a narrowed claim and say so in the pitch.
- **Zero: stop. The premise is unproven and no amount of building fixes that.**

**Done when:** a `fixtures/` directory holds one replayable session and
`findings/reproduced.md` documents each real mismatch with the two file paths and
the exact disagreement.

---

## Days 3-12: the build, in priority order

Each day has a definition of done. If a day runs long, take it from the bottom of
the list, never from days 13-14.

### Day 3-4: Stage 1 checker, one seam kind

Extract from the FastAPI side: route path, method, and the Pydantic request model
with its field names and types. Extract from the React side: fetch target URL,
method, and the body construction (literal object, `JSON.stringify`, `FormData`).
Compare. Emit a finding.

**Done when:** running it against the fixture flags all three reproduced
mismatches and produces no findings on a clean checkout of the same repo.

### Day 5: Baseline and session diff

Compute the merge-base, check it out into a temp worktree, run the checker there,
cache the result by SHA. Subtract the baseline from current findings. Everything
pre-existing becomes invisible.

**Done when:** pointing Irus at a large messy public repo produces zero findings
until you make a change, and then produces exactly one.

### Day 6: Stage 2 execution proof

Tier 1 (build the request, validate against the declared schema, never send it)
and tier 2 (send through the framework test client inside a rolled-back
transaction). Refuse any non-localhost base URL. Refuse real POST/PUT/DELETE over
the wire.

**Done when:** each of the three reproduced mismatches is confirmed by an actual
422 or equivalent, and the database is unchanged afterwards.

### Day 7: Receipts and `irus check`

Render findings as pass/fail receipt lines. Write to the append-only JSONL log.
Add `irus check` with a nonzero exit code so it works as a merge gate and a CI
step.

**Done when:** `irus check` exits 1 on the fixture and 0 on the clean checkout,
and the receipt is readable without any UI.

**Gate C:** at this point the core product works end to end with no graph, no
loop, and no server. If it does not, everything below gets cut and days 8-12 go
into making this solid.

### Day 8: Env var check

Extract `os.environ[...]`, `os.getenv(...)`, `process.env.X` reads from source.
Cross-reference against `.env`, `.env.example`, `docker-compose.yml`,
`vercel.json`, and GitHub Actions `env:` and `secrets:` blocks. Report reads with
no writer.

This is the only piece prior art confirmed is genuinely unoccupied, it works
across every language at near-grep cost, and it produces almost no false
positives. It is worth a full day and its own moment in the demo.

**Done when:** it finds at least one real unset variable in a public repo and the
finding is verifiably true.

### Day 9: Watcher, log, SSE

Watch the working tree (ignore `node_modules`, `.git`, `__pycache__`, `dist`,
`.venv`, and anything in `.gitignore`, or the watcher will storm). Debounce.
Append events. Serve SSE. Replay the whole log on connect.

**Done when:** two terminals editing two worktrees produce live events on a
curl'd SSE stream, and a refresh reproduces identical state.

### Day 10: The graph page

One HTML file. Two layers: baseline dim and unlabeled, session full-colour and
labeled. Deterministic seeded layout. Node size by blast radius. Dashed red arc
for the missing connection, endpoints pulled apart. Colours exactly as specced.

**Done when:** replaying the fixture from an empty canvas produces exactly one red
arc at the moment the second agent finishes, and it is legible from three metres
away.

### Day 11: The loop, the ratchet, the authority rule

Detect, prove, report, dispatch one owner per seam, re-run the full receipt set,
accept the round only if total failures strictly decreased. Cache per-seam results
by content hash of both sides. Producer is authoritative by default; write the
decision into the receipt.

**Done when:** a deliberately induced oscillation (both sides "fixing" toward each
other) is refused by the ratchet rather than looping forever.

### Day 12: The findings ledger

Run the full checker unfiltered against five real public repos. Hand-label every
finding true or false. Commit the whole thing, including the false positives, with
totals stated plainly.

**Done when:** `findings/ledger.md` exists, the true/false split is honest, and
the number is one you are willing to say out loud on stage.

---

## Days 13-14 (LOCKED): rehearsal and buffer

**Day 13:** ten full run-throughs. Wifi off. Unplugged. Fresh terminal each time.
Different screen resolution once. Practise the recovery line for each known
failure mode.

**Day 14:** buffer. It will be used.

---

## Cut order when behind

Cut from the bottom. Never cut upward into days 1-2 or 13-14.

1. The loop and ratchet (day 11), since the demo does not need a fix cycle
2. Blast-radius node sizing
3. The MCP surface entirely
4. Stage 2 tier 2, keeping only tier 1 (build the request, do not send it)
5. The env var check
6. The graph, falling back to a formatted terminal receipt

Everything above the cut line at day 12 must work on the fixture without a network
connection.

---

## Standing rules

- **Never plant a bug and present it as found.** Every demo failure comes from the
  recorded real session.
- **Never demo a live agent.** Replay the fixture.
- **A model may write a test. A model may never judge one.**
- **Never claim zero false positives.** Publish the count.
- **Never weaken a check to make a case pass.** If a check is wrong, fix the check
  and say so.
- Run the full fixture suite after every change.

---

## Risks and their responses

| Risk | Response |
|---|---|
| Payload shape matching turns out to be real type inference and eats a week | Narrow to literal object bodies and `FormData` only. Say so in the pitch. Do not silently overclaim coverage |
| Orphan and env findings flood a real repo | Baseline diff already handles this. If it still floods, ship the confidence tier and gate on high only |
| roam-code or Bernstein ships the same thing mid-build | Position, do not pivot. roam-code prevents by partitioning and never checks compliance; Bernstein needs tests that already exist |
| File watcher storms | Ignore list plus debounce, tested on a repo with a real `node_modules` |
| SSE drops when the laptop sleeps | Replay-on-connect already fixes this. Test it by closing the lid |
| The canvas is empty or a hairball on stage | Two-layer render is the answer; verify legibility at three metres on day 10, not day 13 |
