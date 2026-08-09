# Gate A: do mid-build worktrees boot?

Subject: `Irus`, importing `app.main`.

The clean worktree boots, so the control holds and these results mean
something.

## Result: 3 of 5 applied states still boot

| state | what an agent left behind | boots | predicted beforehand | matched |
|---|---|---|---|---|
| `unwired_route` | new route file written, not yet mounted | yes | boots: an unimported module cannot break the app | yes |
| `missing_import` | route imports a schema module not written yet | no | does not boot: the import fails at startup | yes |
| `undefined_name` | handler calls a helper that does not exist yet | yes | boots: the name is resolved only when the route is called | yes |
| `truncated_edit` | a write cut off mid-statement | no | does not boot: syntax error | yes |
| `widened_model` | a field added to a schema | yes | boots: it is a valid edit | yes |

- `missing_import` failed with: `ModuleNotFoundError: No module named 'app.schemas'`
- `truncated_edit` failed with: `SyntaxError: '(' was never closed`

## What this means for the design

Execution is available in 3 of 5 states and unavailable in the rest. Neither premise holds outright: a checker that works without running the app has real value precisely because the tree is sometimes unbootable, and execution proof has real value precisely because it is often available. That is the two-stage design, and this is the first evidence for it.
