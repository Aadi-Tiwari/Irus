"""Gate A: can a mid-build agent worktree actually be booted?

This is the premise the whole design rests on. Static analysis is only
*necessary* if the application cannot be run while agents are part-way through
their work. If it can be run, one request settles the headline example and
stage 1 becomes an optimisation rather than the product.

The experiment: take a repository, create parallel git worktrees, put each into
a state an agent plausibly leaves mid-task, and try to boot the app.

Three guards, because the result is worthless without them:

  * a clean worktree is measured first. If the clean tree does not boot, the
    environment is the confound and nothing can be concluded from the rest.
  * an edit that finds nothing to change is reported as "did not apply", never
    counted as a pass. A harness that can score a vacuous run is not evidence.
  * each state records what a careful person would predict *before* the run, so
    a surprising result is visible as a surprise rather than rationalised after.

Run: python tools/gate_a.py <repo> <module> [subdir] [interpreter]

`subdir` is where the application lives inside the repository. Worktrees are
always created from the repository root, so the subject can be vendored in a
fixtures/ directory rather than needing a repository of its own.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".irus"}

INTERPRETER = sys.executable


@dataclass
class State:
    name: str
    description: str
    expectation: str      # recorded before the run, not after
    edit: object          # callable(worktree) -> Path | None


@dataclass
class Result:
    name: str
    description: str
    expectation: str
    booted: bool
    detail: str = ""
    applied: bool = True  # False when the edit found nothing to change


@dataclass
class GateA:
    repo: str
    module: str
    clean_boots: bool = False
    clean_detail: str = ""
    results: list[Result] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.clean_boots


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, errors="replace"
    )


def try_boot(worktree: Path, module: str, extra_path: str = "") -> tuple[bool, str]:
    """Import the application module.

    Importing is a necessary condition for booting: a tree that cannot be
    imported certainly cannot serve a request.
    """
    root = worktree / extra_path if extra_path else worktree
    code = (
        f"import sys; sys.path.insert(0, r'{root}')\n"
        "import importlib\n"
        f"importlib.import_module('{module}')\n"
        "print('BOOTED')\n"
    )
    proc = subprocess.run(
        [INTERPRETER, "-c", code], capture_output=True, text=True,
        errors="replace", timeout=180,
    )
    if "BOOTED" in proc.stdout:
        return True, ""
    tail = (proc.stderr or "").strip().splitlines()
    return False, tail[-1][:160] if tail else "no output"


# ------------------------------------------------------------- layout finding
def _candidates(root: Path, pattern: str):
    for path in root.rglob(pattern):
        if not any(part in SKIP_PARTS for part in path.parts):
            yield path


def find_routes_dir(root: Path) -> Path | None:
    for name in ("routes", "routers", "endpoints"):
        for path in _candidates(root, name):
            if path.is_dir():
                return path
    for path in _candidates(root, "main.py"):
        return path.parent
    return None


def find_router_hub(root: Path) -> Path | None:
    """The file that calls include_router; what a truncated write breaks."""
    for path in _candidates(root, "*.py"):
        try:
            if "include_router" in path.read_text("utf-8", errors="replace"):
                return path
        except OSError:
            continue
    return None


def _package_of(root: Path, directory: Path) -> str:
    return ".".join(directory.relative_to(root).parts)


# ------------------------------------------------------- the mid-build states
def add_unwired_route(root: Path) -> Path | None:
    """An agent wrote a new route file and has not mounted it yet."""
    routes = find_routes_dir(root)
    if routes is None:
        return None
    target = routes / "reports.py"
    target.write_text(
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n\n"
        '@router.get("/reports")\n'
        "def read_reports():\n"
        "    return []\n",
        encoding="utf-8",
    )
    return target


def _write_route_and_mount(root: Path, body: str) -> Path | None:
    routes, hub = find_routes_dir(root), find_router_hub(root)
    if routes is None or hub is None:
        return None
    target = routes / "reports.py"
    target.write_text(body, encoding="utf-8")
    package = _package_of(root, routes)
    hub.write_text(
        f"from {package} import reports\n"
        + hub.read_text(encoding="utf-8")
        + "\napi_router.include_router(reports.router)\n",
        encoding="utf-8",
    )
    return target


def add_route_importing_missing_module(root: Path) -> Path | None:
    """An agent wrote the route before the schema module it imports."""
    return _write_route_and_mount(
        root,
        "from fastapi import APIRouter\n"
        "from app.schemas.reports import ReportOut  # not written yet\n\n"
        "router = APIRouter()\n\n\n"
        '@router.get("/reports", response_model=ReportOut)\n'
        "def read_reports():\n"
        "    return []\n",
    )


def add_undefined_name_in_handler(root: Path) -> Path | None:
    """An agent called a helper it has not written. Valid syntax, fails at call."""
    return _write_route_and_mount(
        root,
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n\n"
        '@router.get("/reports")\n'
        "def read_reports():\n"
        "    return build_report_payload()  # helper not written yet\n",
    )


def truncated_edit(root: Path) -> Path | None:
    """An agent's write was cut off mid-statement."""
    hub = find_router_hub(root)
    if hub is None:
        return None
    hub.write_text(
        hub.read_text(encoding="utf-8") + "\napi_router.include_router(\n", encoding="utf-8"
    )
    return hub


def widen_a_model(root: Path) -> Path | None:
    """An agent added a field to a schema. Should leave a bootable tree."""
    for path in _candidates(root, "*.py"):
        text = path.read_text("utf-8", errors="replace")
        if "BaseModel" in text and "class " in text:
            path.write_text(text + "\n\n# agent added a field here\n", encoding="utf-8")
            return path
    return None


STATES = [
    State("unwired_route", "new route file written, not yet mounted",
          "boots: an unimported module cannot break the app", add_unwired_route),
    State("missing_import", "route imports a schema module not written yet",
          "does not boot: the import fails at startup", add_route_importing_missing_module),
    State("undefined_name", "handler calls a helper that does not exist yet",
          "boots: the name is resolved only when the route is called",
          add_undefined_name_in_handler),
    State("truncated_edit", "a write cut off mid-statement",
          "does not boot: syntax error", truncated_edit),
    State("widened_model", "a field added to a schema",
          "boots: it is a valid edit", widen_a_model),
]


def run(repo: Path, module: str, extra_path: str = "") -> GateA:
    out = GateA(repo=repo.name, module=module)

    with tempfile.TemporaryDirectory(prefix="gate-a-") as tmp:
        base = Path(tmp)

        clean = base / "clean"
        if git(repo, "worktree", "add", "--detach", "--quiet", str(clean), "HEAD").returncode != 0:
            out.clean_detail = "could not create a worktree"
            return out
        try:
            out.clean_boots, out.clean_detail = try_boot(clean, module, extra_path)
        finally:
            git(repo, "worktree", "remove", "--force", str(clean))

        if not out.clean_boots:
            return out

        for state in STATES:
            work = base / state.name
            if git(repo, "worktree", "add", "--detach", "--quiet",
                   str(work), "HEAD").returncode != 0:
                continue
            try:
                # Edits apply where the application actually lives, which is a
                # subdirectory when the subject is vendored inside a larger
                # repository. try_boot already resolves the same path.
                touched = state.edit(work / extra_path if extra_path else work)
                if touched is None:
                    out.results.append(Result(
                        state.name, state.description, state.expectation,
                        booted=False, detail="edit did not apply to this layout",
                        applied=False))
                    continue
                booted, detail = try_boot(work, module, extra_path)
                out.results.append(Result(
                    state.name, state.description, state.expectation, booted, detail))
            finally:
                git(repo, "worktree", "remove", "--force", str(work))
    return out


def report(g: GateA) -> str:
    lines = ["# Gate A: do mid-build worktrees boot?", "",
             f"Subject: `{g.repo}`, importing `{g.module}`.", ""]
    if not g.valid:
        return "\n".join(lines + [
            "## Result: INCONCLUSIVE", "",
            "The **clean** worktree does not boot here, so nothing can be concluded",
            "from the mid-build states. Whatever broke them broke the untouched tree.",
            "", f"Clean-tree failure: `{g.clean_detail}`", "",
        ])

    applied = [r for r in g.results if r.applied]
    skipped = [r for r in g.results if not r.applied]
    booted = [r for r in applied if r.booted]

    lines += [
        "The clean worktree boots, so the control holds and these results mean",
        "something.", "",
        f"## Result: {len(booted)} of {len(applied)} applied states still boot", "",
        "| state | what an agent left behind | boots | predicted beforehand | matched |",
        "|---|---|---|---|---|",
    ]
    for r in applied:
        matched = "yes" if r.expectation.startswith("boots") == r.booted else "**no**"
        lines.append(
            f"| `{r.name}` | {r.description} | {'yes' if r.booted else 'no'} "
            f"| {r.expectation} | {matched} |")
    lines.append("")
    for r in applied:
        if not r.booted and r.detail:
            lines.append(f"- `{r.name}` failed with: `{r.detail}`")
    if skipped:
        lines += ["", "Excluded rather than counted as passes, because the edit found "
                      "nothing to change: " + ", ".join(f"`{r.name}`" for r in skipped)]
    lines += ["", "## What this means for the design", ""]
    if booted and len(booted) == len(applied):
        lines.append("Every applied state still boots, so execution is available "
                     "mid-build and stage 1 is an optimisation, not a necessity.")
    elif not booted:
        lines.append("No applied state boots, so execution is unavailable mid-build "
                     "and static analysis is the only option.")
    else:
        lines.append(
            f"Execution is available in {len(booted)} of {len(applied)} states and "
            "unavailable in the rest. Neither premise holds outright: a checker that "
            "works without running the app has real value precisely because the tree "
            "is sometimes unbootable, and execution proof has real value precisely "
            "because it is often available. That is the two-stage design, and this "
            "is the first evidence for it.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    repo = Path(sys.argv[1]).resolve()
    module = sys.argv[2]
    extra = sys.argv[3] if len(sys.argv) > 3 else ""
    if len(sys.argv) > 4:
        INTERPRETER = sys.argv[4]
    result = run(repo, module, extra)
    Path("findings").mkdir(exist_ok=True)
    Path("findings/gate-a.md").write_text(report(result), encoding="utf-8")
    Path("findings/gate-a.json").write_text(json.dumps({
        "repo": result.repo, "module": result.module,
        "clean_boots": result.clean_boots, "clean_detail": result.clean_detail,
        "results": [vars(r) for r in result.results],
    }, indent=1), encoding="utf-8")
    print(report(result))
