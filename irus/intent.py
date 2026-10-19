"""A human-owned project brief with a content-addressed revision."""

from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class Brief:
    path: str
    text: str
    revision: str


def load(root: Path) -> Brief | None:
    path = root / "IRUS.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("IRUS.md is empty. Write the project's goal and acceptance checks before claiming work.")
    revision = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Brief(str(path), text, revision)
