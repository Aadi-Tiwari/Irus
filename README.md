# Irus

**Irus catches the bug that happens between two AI coding agents.**

Agent A builds the checkout endpoint. It expects JSON with `email` and `amount`.
Its tests pass. It reports done, truthfully.

Agent B builds the checkout form. It posts `FormData` with `user_email` and
`total`. Its tests pass. It reports done, truthfully.

Neither agent is wrong about its own half. Neither ever saw the other half. Git
merges both branches without a conflict because they touched different files.
The typechecker validates each side alone and finds nothing. CI runs each branch
against base, never against the other branch. The application is broken and every
signal available says it is fine.

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

## Install

```bash
pip install -e .
```

The engine has **no required dependencies**. It is standard library only, so it
runs with no network, no build step and nothing to install on a fresh machine.
Two optional extras exist and are needed by nothing else:

```bash
pip install -e ".[config]"   # PyYAML, for richer compose and Actions parsing
pip install -e ".[prove]"    # starlette + httpx, for stage-2 execution proof
```

## Use

```bash
irus check                       # sweep; exits 1 on a high-confidence finding
irus check --prove --app main:app   # also execute the suspect seams
irus check --json                # machine readable
irus watch                       # live map at http://127.0.0.1:<port>
irus baseline                    # recompute the merge-base baseline
irus suppress f-1a2b3c --reason "called by the k8s probe"
irus ledger ../repo-a ../repo-b --out findings/
```

## How it works

**It reads both sides and compares what each declares.** Deterministic static
analysis, no model anywhere in the verification path, identical answer every
time. Python is parsed with the standard library `ast`; TypeScript with a
dependency-free scanner that masks strings and comments before any structural
parsing, so a brace inside a string cannot fool it.

**It proves the disagreement by executing it.** Three tiers, cheapest first:
build the request and validate it against the handler's declared schema without
sending anything; drive the real handler in-process through the framework's test
client; and real HTTP for safe methods only. The verdict comes from the
application, not from our checker, which is what makes it evidence.

**It reports only what this session introduced.** The baseline is anchored to the
git merge-base of the active worktrees, never to wall-clock time. Anchoring to
"when the tool started" would hide the bug whenever agents were already working
before the tool was launched, which is the common case and the exact failure the
tool exists to catch.

**It draws the missing connection.** In a normal dependency graph the interesting
thing is the edges that exist. Here it is the edge that should exist and does
not, and absence is invisible by default, so it is drawn explicitly as a dashed
red arc with the two ends pulled apart.

## What it will not do

- **It never claims zero false positives.** `irus ledger` runs unfiltered across
  real repositories and publishes every finding for hand labelling, including the
  wrong ones. A tool that publishes only its hits is not measurable, and a claim
  of perfection dies to one counterexample.
- **A model may write a test. A model never decides whether a test passed.**
- **Nothing leaves your machine.** No network, no telemetry, no accounts.
- **Execution is opt-in and cannot escape.** Nothing is sent off localhost, no
  mutating method ever travels over the wire, and the local store is
  fingerprinted before and after every proof run. A change aborts loudly rather
  than being reported as a pass.
- **Unknown is never high confidence.** A body assembled through a helper the
  scanner cannot follow is reported as unknown, because that is our limitation
  rather than the code's defect. A spread (`...rest`) suppresses missing-field
  checks for that seam instead of guessing.

## As an MCP server

Agents read the map as text, never as a picture. Register it with any MCP client:

```json
{
  "mcpServers": {
    "irus": {
      "command": "irus-mcp",
      "args": ["/path/to/your/repo"]
    }
  }
}
```

The path argument is optional; without it the server uses its working directory,
and every tool also accepts a `path` so one server can serve any repository.

Four tools: `status` (seams that disagree, routes nobody calls, environment
variables read but never set), `next` (claim one unclaimed piece of work),
`claim` and `release`.

JSON-RPC 2.0 over stdio, standard library only, no network. Protocol versions
2024-11-05, 2025-03-26 and 2025-06-18 are all accepted and the client's choice
is echoed back. 15 conformance tests drive it as a subprocess exactly as a
client would, including stdout purity, launching from an unrelated working
directory, keepalive pings, malformed input, and tool failures.

## Measured

On this machine, against a synthetic 500-file project:

| | measured | budget |
|---|---|---|
| Full sweep, 500 source files | 0.28s best, 0.51s median | 2.0s |
| Incremental re-check after one edit | 83ms best, 105ms median | 200ms |

164 tests pass. Run them with `pytest`.

**Precision, measured against five repositories nobody here wrote** (dispatch,
flower, full-stack-fastapi-template, redash, reflex): **72.1% over 226 judged
findings.** Every finding, including the wrong ones, is published in
`findings/ledger.md`.

| check | n | precision |
|---|---|---|
| `env_unset` | 70 | 97% |
| `orphan_component` | 89 | 93% |
| `orphan_endpoint` | 155 | 18% |

Labels come from a different method than the one that produced the findings:
the scanner works from parsed syntax, `tools/adjudicate.py` works from raw text
search. `orphan_endpoint` is weak, is reported at low confidence because of it,
and is deliberately not tuned further, since the remaining improvement available
is to match paths the way the adjudicator judges them, which would drive the
published number toward 100% by construction and measure nothing.

**Both gates are answered**, in `findings/gate-a.md` and
`findings/reproduced.md`. Three of five realistic mid-build worktree states
still boot, so execution is sometimes available and sometimes not, which is why
there are two stages. And two agents given one half each of a prose spec, in
separate worktrees with no knowledge of each other, produced a real mismatch
that git merged clean: one wrote `marketing_emails`, the other
`marketing_opt_in`. That session is committed under `fixtures/gate-b-session/`.

## Honestly unverified

**One mismatch, from one session, over three features.** Enough to show the tool
catches something real, nowhere near enough to estimate a rate. Two of the three
features matched exactly.

**Both agents were Claude subagents on one machine**, not two vendors on two
laptops. The mechanism is faithfully reproduced; the vendor diversity is not.

**The premise is weaker than the pitch says.** The frontend agent did not report
unqualified success: it flagged that it had invented the whole contract and
asked for a shared one. The mismatch still survived the merge and every other
check, but "neither agent suspects anything" is not what happened.

**Client indirection is followed one hop only.** A body assembled through a
chain the scanner cannot follow is reported as unknown rather than guessed at,
so recall on heavily abstracted client code is lower than on a direct call, and
that gap is not quantified.
