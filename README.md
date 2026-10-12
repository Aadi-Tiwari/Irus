# Irus

Find integration mismatches across Python and TypeScript code before they reach a running application.

A server can expect JSON fields named `email` and `amount` while a client sends form fields named `user_email` and `total`. Each side may pass its own tests. Irus compares both sides, reports the incompatible contract, and can optionally exercise the suspected mismatch against a local application.

## Install

Use Python 3.11 or newer.

```sh
python -m pip install -e ".[dev]"
```

The core scanner and coordination server use the Python standard library. Optional extras add YAML parsing (`.[config]`) and local ASGI execution checks (`.[prove]`). Install the application's own dependencies separately when using execution checks.

## Check a project

```sh
irus check
irus check --json
irus check --prove --app main:app
irus watch
```

`check` reports new findings relative to the Git baseline and exits unsuccessfully when high-confidence findings remain. `watch` serves the live map on loopback. Run `irus --help` or a command's `--help` for its full options.

```sh
irus baseline
irus suppress FINDING_ID --reason "Called by the deployment health probe"
irus ledger ../repo-a ../repo-b --out findings/
```

Static checks inspect declared routes, client calls, payloads, configuration, and components. An unresolved expression is a scanner limitation, not proof of a bug. `--prove` executes local application code; use it only on a project you trust. It is not an operating-system sandbox.

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

The stdio server exposes `status`, `next`, `claim`, and `release`. The path argument is optional; the default is the server's working directory.

## Evidence and limitations

Recorded findings and experiments are in [findings/](findings/), including the [ledger](findings/ledger.md), [execution gate](findings/gate-a.md), and [reproduction notes](findings/reproduced.md). These are historical observations, not a current accuracy guarantee.

The recorded agent experiment used the same model family on one machine. It demonstrates a contract mismatch, not broad evidence across vendors or teams. The frontend participant also flagged uncertainty about the shared contract. Client indirection is followed only to the depth supported by the scanner, and orphan-route findings can have false positives.

## Tests

```sh
python -m pytest -q
```

Tests cover extraction, matching, baselines, execution checks, room behavior, file access, MCP, and explicit hosting consent. No model credentials are needed for the test suite.
