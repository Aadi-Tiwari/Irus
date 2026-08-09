"""The file watcher.

    B-R16  Ignores `node_modules`, `.git`, `__pycache__`, `dist`, `.venv`, and
           everything in `.gitignore`, and debounces bursts.
    B-R14  Incremental re-check after a single file change completes in under
           200 milliseconds.

Polling by mtime rather than a native watch API. On a tree already pruned by the
ignore list this is a few thousand `stat` calls, which is cheap, and it has no
dependency and no platform-specific failure mode — a watcher that dies silently
on one OS is worse than one that polls.

The debounce is not a nicety. An agent writing a file, a formatter rewriting it,
and a bundler touching its output arrive as three events for one logical change;
without coalescing, the sweep runs three times and the page flickers through two
states that never really existed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .walk import SOURCE_SUFFIXES, source_files

DEFAULT_DEBOUNCE = 0.25      # seconds of quiet before a burst is considered over
DEFAULT_INTERVAL = 0.20      # seconds between polls


@dataclass
class Change:
    added: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.added or self.modified or self.removed)

    @property
    def paths(self) -> set[str]:
        return self.added | self.modified | self.removed

    def merge(self, other: "Change") -> "Change":
        """Coalesce a burst, `self` then `other`, by replaying `other`'s events
        onto `self`'s state.

        Written as sequencing rather than set algebra because the interesting
        cases are order-dependent: added-then-removed cancels entirely (which is
        what stops an editor's temp file from ever reaching the log), while
        removed-then-added is a modification, not a fresh file.
        """
        added = set(self.added)
        modified = set(self.modified)
        removed = set(self.removed)

        for path in other.added:
            if path in removed:
                removed.discard(path)
                modified.add(path)          # removed then re-added: a rewrite
            else:
                added.add(path)
        for path in other.removed:
            if path in added:
                added.discard(path)          # created and gone: never happened
            else:
                modified.discard(path)
                removed.add(path)
        for path in other.modified:
            if path not in added and path not in removed:
                modified.add(path)

        return Change(added=added, modified=modified, removed=removed)


class Watcher:
    def __init__(
        self,
        root: str | Path,
        *,
        debounce: float = DEFAULT_DEBOUNCE,
        interval: float = DEFAULT_INTERVAL,
        suffixes: Iterable[str] = SOURCE_SUFFIXES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = Path(root).resolve()
        self.debounce = debounce
        self.interval = interval
        self.suffixes = frozenset(suffixes)
        self._clock = clock
        self._state: dict[str, float] = {}
        self.polls = 0
        self.snapshot()

    def _scan(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for path in source_files(self.root, frozenset(self.suffixes)):
            try:
                out[str(path.relative_to(self.root))] = path.stat().st_mtime
            except OSError:
                continue
        return out

    def snapshot(self) -> None:
        """Reset the baseline without emitting anything."""
        self._state = self._scan()

    def poll(self) -> Change:
        """One comparison against the last snapshot. Not debounced — `watch`
        does that."""
        self.polls += 1
        current = self._scan()
        previous = self._state
        added = set(current) - set(previous)
        removed = set(previous) - set(current)
        modified = {p for p in set(current) & set(previous) if current[p] != previous[p]}
        self._state = current
        return Change(added=added, modified=modified, removed=removed)

    def watch(self, on_change: Callable[[Change], None], *, stop: Callable[[], bool] = lambda: False) -> None:
        """Block, calling `on_change` once per settled burst."""
        pending = Change()
        last_event = 0.0
        while not stop():
            change = self.poll()
            now = self._clock()
            if change:
                pending = pending.merge(change)
                last_event = now
            elif pending and (now - last_event) >= self.debounce:
                settled, pending = pending, Change()
                on_change(settled)
            time.sleep(self.interval)
        if pending:
            on_change(pending)
