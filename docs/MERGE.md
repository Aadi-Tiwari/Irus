# Merging Part A and Part B

Two complete implementations of the same product existed: this tree (Part A,
plus the Part B engineering requirements) and the `part-b` branch. They were not
a library and a plugin. They were two `irus/` packages that overlapped on
baseline, cli, prove, receipts, ledger, extraction and the page.

That is the failure this project exists to detect, arriving on our own doorstep,
and it is worth stating plainly rather than glossing.

## What was kept, and why

**Base: this tree.** Two reasons, both checkable.

1. Coverage. The `part-b` branch implements no second stack (A-R7), no MCP
   surface (A-R22), no coordination, authority rule or ratchet (A-R23 to A-R25),
   no orphan-component detection and no response-shape comparison (A-R5, part of
   A-R6). Part A is roughly half unimplemented there.
2. Performance. On the same machine the `part-b` branch fails its own two
   performance requirements: `test_b_r13_full_sweep_of_500_files_under_2_seconds`
   and `test_b_r14_incremental_recheck_under_200ms` (720 ms against a 200 ms
   budget). 65 of its 67 tests pass. This tree meets both budgets, measured.

## What was adopted from `part-b`, because it is better

Three mechanisms, ported rather than copied:

- **`MissingEvidence`.** A finding is validated at construction: it must carry a
  specific disagreement and at least one concrete file site. B-R19 becomes
  impossible to violate rather than something checked downstream. This found and
  removed eighteen evidence-free findings in our own test fixtures.
- **`AppendOnlyViolation` and `canonical()`.** `t`, `kind` and `seq` are stamped
  by the log and rejected if a caller supplies them, `kind` is positional-only so
  the rejection is the append-only error rather than a bare `TypeError`, and
  events serialise byte-identically so B-R4 can be asserted on bytes.
- **The consent gate.** A command-line flag is consent for one run; the recorded
  `.irus/consent.json` is consent given knowingly once and revoked by deleting a
  file. Strictly stronger than a bare `--prove` flag for B-R12.

`assert_transport(method, transport)` was also adopted, folding two separate
guards into one rail.

## What was taken wholesale, because it does not conflict

`docs/PART-B-CONFORMANCE.md`, `docs/DEMO.md`, `findings/`, `fixtures/` and
`tools/`. The most valuable of these is `findings/reproduced.md`, which records
that **Gate B has zero reproduced mismatches and is not passed.** That is the
honest answer to the question the whole build plan is gated on, and it was
written by the teammate, not by us.

## What was dropped

The `part-b` `irus/` package itself, and its 702-line `tests/test_part_b.py`,
which binds to module names that no longer exist. The requirements those tests
cover are covered here under different names. That is a real loss of independent
test wording, and it is recorded rather than hidden.
