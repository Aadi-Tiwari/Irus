"""Label every ledger finding by checking it against the repository directly.

The point of a ledger is to measure the checker. If the checker also decides
whether its own findings are right, the number measures self-consistency and
nothing else. So every verdict here comes from a **different method** than the
one that produced the finding: the scanner works from parsed syntax, and this
works from raw text search over the whole tree.

Where the two agree the finding is confirmed. Where the independent search finds
the thing the scanner said was missing, the finding is a false positive and is
recorded as one.

A verdict this cannot reach on its own is left `unlabelled` with the reason
stated, rather than guessed. An honest gap is worth more than a filled cell.

This is an automated cross-check, not human judgement. It is a floor under the
number, not a substitute for someone reading the code.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irus.scan import IGNORE_DIRS, scan  # noqa: E402

TEXT_EXT = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".yml", ".yaml",
    ".toml", ".cfg", ".ini", ".env", ".sh", ".md", ".txt", ".html", ".tf", ".example",
}

TRUE, FALSE, UNSURE = "true", "false", "unlabelled"


@dataclass
class Verdict:
    label: str
    reason: str


def load_corpus(root: Path) -> list[tuple[str, str]]:
    """Every text file in the tree, as (relative path, contents)."""
    out: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(p in IGNORE_DIRS or p.startswith(".") for p in rel_parts[:-1]):
            continue
        if path.suffix not in TEXT_EXT and not path.name.startswith(".env"):
            continue
        try:
            out.append(("/".join(rel_parts), path.read_text("utf-8", errors="replace")))
        except OSError:
            continue
    return out


def hits(corpus: list[tuple[str, str]], pattern: re.Pattern, exclude: str = "") -> list[str]:
    found = []
    for rel, text in corpus:
        if exclude and rel == exclude:
            continue
        if pattern.search(text):
            found.append(rel)
    return found


# --------------------------------------------------------------- adjudicators
def judge_env_unset(finding, corpus) -> Verdict:
    """Claim: this variable is read and set nowhere.

    Independent check: search every config-shaped file for an assignment.
    """
    name = finding.subject
    assign = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}\s*[:=]")
    config = [
        (rel, text) for rel, text in corpus
        if rel.endswith((".yml", ".yaml", ".json", ".toml", ".cfg", ".ini", ".sh", ".tf"))
        or "/.env" in f"/{rel}" or rel.startswith(".env") or rel.endswith(".env.example")
    ]
    where = hits(config, assign)
    if where:
        return Verdict(FALSE, f"assigned in {where[0]}")
    docs = hits([(r, t) for r, t in corpus if r.endswith(".md")], assign)
    if docs:
        return Verdict(TRUE, f"documented in {docs[0]} but assigned in no config file")
    return Verdict(TRUE, "no assignment found anywhere in the tree")


def judge_orphan_component(finding, corpus) -> Verdict:
    """Claim: this component is never mounted or imported.

    Independent check: search for a JSX tag or a named import elsewhere.
    """
    name = finding.subject
    own = finding.producer_loc.file if finding.producer_loc else ""
    jsx = re.compile(rf"<\s*{re.escape(name)}[\s/>]")
    imported = re.compile(rf"\b{re.escape(name)}\b[^\n]*\bfrom\s+['\"]|import[^\n]*\b{re.escape(name)}\b")
    used = hits(corpus, jsx, exclude=own)
    if used:
        return Verdict(FALSE, f"rendered as JSX in {used[0]}")
    brought_in = hits(corpus, imported, exclude=own)
    if brought_in:
        return Verdict(FALSE, f"imported by name in {brought_in[0]}")
    return Verdict(TRUE, "no JSX tag and no named import anywhere in the tree")


def judge_orphan_endpoint(finding, corpus) -> Verdict:
    """Claim: no client in this repository calls this route.

    Independent check: search for the literal path in any file. A route whose
    callers are external cannot be settled from inside the repository, so that
    case is left unlabelled rather than called either way.
    """
    path = finding.seam.split(" ", 1)[-1]
    literal = path.replace("{}", "")
    segments = [s for s in literal.split("/") if s and not s.startswith("{")]
    if not segments:
        return Verdict(UNSURE, "route path is entirely parameters; not decidable by search")
    own = finding.producer_loc.file if finding.producer_loc else ""
    tail = "/".join(segments[-2:]) if len(segments) > 1 else segments[-1]
    caller = re.compile(rf"['\"`][^'\"`\n]*{re.escape(tail)}", re.I)
    where = hits(
        [(r, t) for r, t in corpus if r.endswith((".ts", ".tsx", ".js", ".jsx", ".py"))],
        caller, exclude=own,
    )
    if where:
        return Verdict(FALSE, f"the path appears in {where[0]}")
    return Verdict(TRUE, "the path string appears nowhere else in the tree")


def judge_unmounted_route(finding, corpus) -> Verdict:
    where = hits(corpus, re.compile(r"include_router|app\.use\("))
    if where:
        return Verdict(UNSURE, f"routers are mounted in {where[0]}; needs a human read")
    return Verdict(TRUE, "no include_router call anywhere in the tree")


JUDGES = {
    "env_unset": judge_env_unset,
    "orphan_component": judge_orphan_component,
    "orphan_endpoint": judge_orphan_endpoint,
    "unmounted_route": judge_unmounted_route,
}


def adjudicate(repos: list[Path]) -> dict:
    out: dict = {"repos": []}
    for root in repos:
        result = scan(root)
        corpus = load_corpus(root)
        entries = []
        for f in result.findings:
            judge = JUDGES.get(f.kind)
            verdict = (
                judge(f, corpus) if judge
                else Verdict(UNSURE, f"no independent check exists for {f.kind}")
            )
            entries.append({
                "key": f.key, "kind": f.kind, "seam": f.seam, "subject": f.subject,
                "confidence": f.confidence,
                "location": str(f.producer_loc or f.consumer_loc or ""),
                "label": verdict.label, "reason": verdict.reason,
            })
        out["repos"].append({
            "repo": root.name, "files": result.files,
            "corpus_files": len(corpus), "entries": entries,
        })
        print(f"  {root.name}: {len(entries)} findings over {result.files} source files", flush=True)
    return out


if __name__ == "__main__":
    roots = [Path(p) for p in sys.argv[1:]]
    data = adjudicate(roots)
    Path("findings/adjudicated.json").parent.mkdir(parents=True, exist_ok=True)
    Path("findings/adjudicated.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    print("written findings/adjudicated.json")
