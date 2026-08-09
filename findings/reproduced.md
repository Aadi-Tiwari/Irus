# Reproduced mismatches — Gate B

**Status as of 9 Aug 2026: zero reproduced. Gate B is not passed.**

BUILD-PLAN days 1-2 are locked and non-negotiable, and Gate B is one of the two
things they exist to answer:

> **Gate B: can three real mismatches be reproduced?** From the recorded session
> or from prior history, find three genuine cases where two agents produced
> incompatible sides and both reported success.
>
> - Three or more: proceed.
> - One or two: proceed with a narrowed claim and say so in the pitch.
> - **Zero: stop. The premise is unproven and no amount of building fixes that.**

This file is the artifact that gate produces. It is empty because no recorded
parallel-agent session exists yet.

## What that means for everything else in this repository

The machinery is built and tested. The evidence is not. Concretely:

- The pitch's headline claim is **unsupported by our own data**. The 58%→25%
  figure is third-party (arXiv 2603.24284) and stands on its own; what is missing
  is any demonstration that *this checker* catches *that class* in a real session.
- `fixtures/synthetic-checkout/` was written by hand and is marked `SYNTHETIC`.
  Per B-R26 it must never be presented as a found bug, and `tools/demo.py`
  refuses to replay it without an explicit acknowledgement flag.
- The five-repo run in `ledger.md` is real, but it measures the checker against
  arbitrary open-source code, not against agent-produced mismatches. It is
  evidence about false positives, not evidence about the premise.

## What has to happen to fill this file

1. Take a small real full-stack project.
2. Run agents on it in parallel git worktrees, each given one half of one
   feature, with no shared context.
3. Record every filesystem event to JSONL while they work.
4. Answer **Gate A** at the same time: try to boot the app in each worktree
   mid-session. If it boots, stage 2 is the product and stage 1 is an
   optimisation — that is a cheaper product, not a failure, and the pitch gets
   rewritten around execution.
5. Find the cases where both agents reported success and the halves disagree.

Then document each one below, with the two file paths and the exact
disagreement — not a summary of it.

## Template

```
### 1. <seam>

- producer: <path>:<line> declares <what>
- consumer: <path>:<line> sends <what>
- disagreement: <the exact incompatibility, in one sentence>
- both agents reported success: yes / no
- caught by stage 1: yes / no
- confirmed by stage 2: yes / no, <status code>
- session: fixtures/<recording>.jsonl, events <n>–<m>
```

(No entries.)
