"""B-R18: a suppression file, so a known false positive can be silenced once.

Every entry must carry a reason. A suppression list without reasons decays into
a list nobody dares to delete, and the reason is what lets a later reader decide
whether the suppression is still true.

Suppressions are recorded against the finding key, which is stable across line
movement, so silencing a finding does not un-silence itself on the next edit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .model import Finding

FILENAME = "suppress.json"


@dataclass(frozen=True)
class Rule:
    key: str
    reason: str
    seam: str = ""
    kind: str = ""


class Suppressions:
    def __init__(self, rules: dict[str, Rule] | None = None, path: Path | None = None) -> None:
        self.rules = rules or {}
        self.path = path

    # ---- io --------------------------------------------------------------
    @classmethod
    def load(cls, root: Path) -> "Suppressions":
        path = Path(root) / ".irus" / FILENAME
        if not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls(path=path)
        rules: dict[str, Rule] = {}
        for entry in raw.get("suppress", []):
            key = str(entry.get("key", "")).strip()
            reason = str(entry.get("reason", "")).strip()
            if not key or not reason:
                # A suppression with no reason is refused rather than honoured.
                continue
            rules[key] = Rule(
                key=key,
                reason=reason,
                seam=str(entry.get("seam", "")),
                kind=str(entry.get("kind", "")),
            )
        return cls(rules, path=path)

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "suppress": [
                {"key": r.key, "kind": r.kind, "seam": r.seam, "reason": r.reason}
                for r in sorted(self.rules.values(), key=lambda r: (r.kind, r.seam, r.key))
            ]
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # ---- use -------------------------------------------------------------
    def add(self, finding: Finding, reason: str) -> Rule:
        if not reason.strip():
            raise ValueError("a suppression must carry a reason")
        rule = Rule(finding.key, reason.strip(), finding.seam, finding.kind)
        self.rules[finding.key] = rule
        return rule

    def apply(self, findings: list[Finding]) -> tuple[list[Finding], list[tuple[Finding, Rule]]]:
        kept: list[Finding] = []
        silenced: list[tuple[Finding, Rule]] = []
        for f in findings:
            rule = self.rules.get(f.key)
            if rule is None:
                kept.append(f)
            else:
                silenced.append((f, rule))
        return kept, silenced

    def __len__(self) -> int:
        return len(self.rules)
