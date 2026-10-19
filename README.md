# Irus

Find integration mismatches across Python and TypeScript code before they reach a running application.

The current direction is recorded in [IRUS.md](IRUS.md): integration checking is the core, with a shared project brief to keep coding agents working toward the same goal. Earlier hackathon plans describe a broader ambition; they are not claims that every feature works.

A server can expect JSON fields named `email` and `amount` while a client sends form fields named `user_email` and `total`. Each side may pass its own tests. Irus compares both sides, reports the incompatible contract, and can optionally exercise the suspected mismatch against a local application.

## Install

Use Python 3.11 or newer.

```sh
python -m pip install .
```

The core scanner and coordination server use the Python standard library. Optional extras add YAML parsing (`.[config]`) and local ASGI execution checks (`.[prove]`). Install the application's own dependencies separately when using execution checks.

## Check a project

```sh
irus check /path/to/project --no-baseline
irus check /path/to/project --no-baseline --json
irus watch /path/to/project --no-baseline
```

`check` reports new findings relative to the Git baseline and exits unsuccessfully when high-confidence findings remain. `watch` serves the live map on loopback. Run `irus --help` or a command's `--help` for its full options.

Start with `--no-baseline` to inspect existing code, including committed issues. Without it, the Git baseline deliberately suppresses pre-existing findings. After changing the code, rerun the same command to verify the repair. The live page replaces its findings after each scan, so resolved problems disappear. Use `--refresh-baseline` after upgrading the scanner.

### Check work before merging

```sh
irus check ../backend --with ../frontend --json
```

Repeat `--with` for additional worktrees of the same Git repository. Irus exports their common ancestor to a temporary directory, overlays committed and current uncommitted changes, and checks the combined source. Reports point to the original worktree files. It does not merge, commit, or edit those worktrees. Different changes to the same file stop with an explicit conflict, even if Git could merge them. Resolve that overlap yourself before checking again. Submodules and changed symbolic links are unsupported.

The baseline is the common ancestor of the selected worktrees. Use `--no-baseline` to include pre-existing issues. Combined checks are static only; `--with` cannot be combined with `--prove`. The live watcher currently watches one directory.

For optional execution checks, install `python -m pip install ".[prove]"` and your application's dependencies, then run:

```sh
irus check /path/to/project --no-baseline --prove --yes --app main:app --json
```

`--yes` records consent to execute that project's code. Results distinguish schema comparison from actual application execution. Each proof is `pass`, `fail`, or `unavailable`; a missing dependency, failed import, unreachable server, or refused redirect is unavailable, never a pass. JSON includes proof records and source locations.

Exit codes: `0` means no high-confidence findings remain and all requested checks could run; `1` means findings remain; `2` means a requested check was unavailable or the command failed. Execution is restricted to suspect routes found by the static scanner, so a clean scan does not mean every route was exercised. HTTP execution checks do not follow redirects.

```sh
irus baseline
irus suppress FINDING_ID --reason "Called by the deployment health probe"
irus ledger ../repo-a ../repo-b --out findings/
```

Static checks inspect declared routes, client calls, payloads, configuration, and components. An unresolved expression is a scanner limitation, not proof of a bug. FastAPI routes use module-scoped imports, models, and nested router mounts; unresolved prefixes and ambiguous endpoints are reported as incomplete checks.

Execution probes use generated placeholder values, so a rejected request does not establish why the real application fails. `--prove` imports and executes application code, which can write data or contact external services even through an in-process test client. Local store fingerprints can detect selected file changes after execution but cannot undo them. Use a disposable application and disposable data. There is no transaction rollback or operating-system sandbox.

## Collaborate in a room

```sh
irus host
irus join ROOM_CODE
```

Hosting exposes the coordination room to reachable peers and prints a token-bearing join code. Treat the code as a credential. File access is disabled by default.

To explicitly let room participants read and edit project files:

```sh
irus host --share-files
```

Participants can then use `irus join ROOM_CODE --pull ./theirs`, edit the local checkout, and send their changed files with `--push ./theirs`. File sharing grants remote write access. Use it with trusted collaborators on a trusted network. The legacy `--no-files` option remains accepted.

## MCP interface

After installing the package, configure a compatible client to launch:

```json
{
  "mcpServers": {
    "irus": {
      "command": "irus-mcp",
      "args": ["/path/to/project"]
    }
  }
}
```

The stdio server exposes `brief`, `status`, `next`, `claim`, `release`, and `complete`. The path argument is optional; the default is the server's working directory. MCP clients on the same machine coordinate through a locked `.irus/claims.jsonl` log. A busy client gets a retry message. Claims are advisory: they do not prevent direct file edits. Historical claims in `events.jsonl` are not imported; reclaim active work after upgrading.

Write your project's goal, boundaries, and acceptance checks in `IRUS.md`. `irus brief /path/to/project` or the MCP `brief` tool returns its text and content revision. When the file exists, agents must supply that revision as `brief_revision` to `next`, `claim`, and `complete`. A changed brief invalidates earlier acknowledgements. Projects without a brief retain the existing claiming workflow.

`status`, `next`, and `claim` accept a `worktrees` array and `no_baseline` boolean. Status and the CLI use the same baseline and suppression rules. `complete` rescans the worktrees recorded with the claim, including baseline and suppressed findings for that contract. It releases the claim only when both sides remain present, the request shape is readable, and no findings remain on the claimed HTTP contract. This verifies the supported static contract, not runtime or business behavior. If a route was intentionally renamed or the target is not an HTTP contract, use `release` and verify that change with the project's tests.

Finding IDs now include producer and consumer filenames so an old caller's baseline cannot hide a new caller's defect. Cached baselines invalidate automatically when the scanner changes. Recreate any old ID-based suppressions after reviewing the current findings.

## Evidence and limitations

Recorded findings and experiments are in [findings/](findings/), including the [ledger](findings/ledger.md), [execution gate](findings/gate-a.md), and [reproduction notes](findings/reproduced.md). These are historical observations, not a current accuracy guarantee.

The recorded agent experiment used the same model family on one machine. It demonstrates a contract mismatch, not broad evidence across vendors or teams. The frontend participant also flagged uncertainty about the shared contract. Client indirection is followed only to the depth supported by the scanner, and orphan-route findings can have false positives.

## Tests

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
```

Tests cover extraction, matching, baselines, execution checks, room behavior, file access, MCP, and explicit hosting consent. No model credentials are needed for the test suite.

## License

Original project source is available under the [MIT License](LICENSE). Third-party dependencies, model weights, fonts, documents, and datasets retain their own licenses. This license does not grant rights to third-party assets.
