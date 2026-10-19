# Irus product brief

Irus is a local integration checker for projects built by people and coding agents. Its core job is to catch disagreements between parts that look correct in isolation, show the source evidence, and recheck a repair.

The first usable workflow is a Python API and a JavaScript or TypeScript caller developed in separate Git worktrees. Irus inspects their combined changes before a merge, without changing either checkout. A backend expecting JSON `email` and `amount` must be checked against the frontend's actual declared request shape.

Shared intent supports that workflow. A human-owned `IRUS.md` records the project goal, boundaries, and acceptance checks. Agents read its current revision through MCP before claiming work. Updating the brief requires them to acknowledge the new revision before completing work. This records acknowledgement; it does not prove that an agent understood the idea.

## Acceptance checks

- An incompatible request reports its endpoint, caller, specific disagreement, and source locations in the original worktrees.
- Conflicting versions of a file stop composition with an explicit error. Source worktrees remain unchanged.
- A repaired contract is rescanned before its claim can be completed. Deleting a caller or leaving its payload unresolved does not count as a verified repair.
- A missing dependency or failed execution check is unavailable, never a pass. Schema comparison and runtime execution are reported separately.
- Core scanning, the live map, project briefs, and MCP coordination work without an API key.

## Boundaries

Integration checking is the product's core. Shared briefs and claims keep agents aligned around that work. Do not turn Irus into a general task manager, model router, or autonomous code-writing service.

The first release supports the code patterns implemented by the Python and TypeScript extractors. Dynamic routes, ambiguous imports, arbitrary languages, business correctness, and semantic adherence to a brief are not guaranteed. A clean static scan is not a substitute for application tests.

Remote room and file-sharing code remains available as an experimental collaboration path. Hosted rooms, internet deployment, automatic merging, autonomous repairs, and production execution probes are outside this release. Earlier hackathon specifications are historical context, not a list of completed features.
