"""Findings, confidence tiers, and suppression.

    B-R17  Findings carry a confidence tier. Only high-confidence findings
           fail the merge gate.
    B-R18  A suppression file exists so a user can permanently silence a known
           false positive with a reason recorded.
    B-R19  Every finding names both file paths and the exact disagreement,
           never a generic warning.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

# Ordered worst-to-best so `TIERS.index` doubles as a severity sort key.
TIERS = ("high", "medium", "low")

# Only this tier fails the gate (B-R17). Named rather than inlined so the
# single place it is decided is greppable.
GATING_TIER = "high"


class MissingEvidence(Exception):
    """A finding was constructed without both sides or without a specific
    disagreement. B-R19 is enforced at construction so a generic warning
    cannot reach a receipt."""


@dataclass(frozen=True)
class Side:
    """One half of a seam: which file, which line, what it declares."""

    path: str
    line: int
    declares: str

    def render(self) -> str:
        return f"{self.path}:{self.line} declares {self.declares}"


@dataclass(frozen=True)
class Finding:
    seam: str                 # "POST /api/checkout"
    cls: str                  # payload_mismatch | env_unset | orphan_endpoint
    confidence: str           # high | medium | low
    detail: str               # the exact disagreement, in words
    producer: Side | None     # the declaring side (may be None for env findings)
    consumer: Side | None     # the calling side
    evidence: dict[str, Any]  # machine-readable shapes, for the log and the page

    def __post_init__(self) -> None:
        if self.confidence not in TIERS:
            raise ValueError(f"unknown confidence tier: {self.confidence!r}")
        if not self.detail or len(self.detail) < 12:
            raise MissingEvidence(f"{self.seam}: detail is not a specific disagreement (B-R19)")
        if self.producer is None and self.consumer is None:
            raise MissingEvidence(f"{self.seam}: a finding must name at least one concrete site (B-R19)")

    @property
    def id(self) -> str:
        """Stable identity: a content hash of what the finding is about, not
        of when it was found. The same disagreement gets the same id on every
        machine and every run, which is what makes suppressions and the
        per-seam cache durable (B-R1, B-R15, B-R18)."""
        material = "|".join(
            [
                self.cls,
                self.seam,
                self.producer.path if self.producer else "-",
                self.consumer.path if self.consumer else "-",
            ]
        )
        return "seam-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]

    @property
    def paths(self) -> list[str]:
        return [s.path for s in (self.producer, self.consumer) if s is not None]

    def gates(self) -> bool:
        """Does this finding fail `irus check`? (B-R17)"""
        return self.confidence == GATING_TIER

    def sort_key(self) -> tuple:
        """Deterministic total order. Severity first, then identity — never
        discovery order, which would depend on filesystem walk order (B-R1)."""
        return (TIERS.index(self.confidence), self.cls, self.seam, self.id)

    def to_event(self) -> dict[str, Any]:
        """The `finding` event shape from PRD-B section 2."""
        return {
            "id": self.id,
            "seam": self.seam,
            "class": self.cls,
            "confidence": self.confidence,
            "detail": self.detail,
            "paths": self.paths,
            "producer": asdict(self.producer) if self.producer else None,
            "consumer": asdict(self.consumer) if self.consumer else None,
            "evidence": self.evidence,
        }


# --------------------------------------------------------------- suppression


class Suppressions:
    """`.irus/suppressions.json`. A reason is mandatory — a suppression with no
    recorded reason is indistinguishable from a bug being hidden, so this
    refuses to write one (B-R18)."""

    FILENAME = Path(".irus") / "suppressions.json"

    def __init__(self, root: str | Path) -> None:
        self.path = Path(root) / self.FILENAME
        self.entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        for entry in raw.get("suppressed", []):
            fid = entry.get("id")
            if fid and entry.get("reason"):
                self.entries[str(fid)] = entry

    def add(self, finding_id: str, reason: str) -> None:
        if not reason or not reason.strip():
            raise ValueError("a suppression requires a recorded reason (B-R18)")
        self.entries[finding_id] = {"id": finding_id, "reason": reason.strip()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"suppressed": [self.entries[k] for k in sorted(self.entries)]}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def __contains__(self, finding_id: object) -> bool:
        return str(finding_id) in self.entries

    def reason(self, finding_id: str) -> str | None:
        entry = self.entries.get(finding_id)
        return entry.get("reason") if entry else None

    def apply(self, findings: Iterable[Finding]) -> tuple[list[Finding], list[Finding]]:
        """Split into (kept, suppressed). Suppressed findings are returned, not
        discarded, so the receipt can still say how many were silenced —
        a hidden count is how a suppression file becomes a lie."""
        kept, hidden = [], []
        for f in findings:
            (hidden if f.id in self else kept).append(f)
        return kept, hidden
