"""Compose selected worktrees in a temporary directory without merging branches."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile

from .baseline import GitError, git


class CompositionError(RuntimeError):
    pass


def git_bytes(root: Path, *args: str) -> bytes:
    process = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if process.returncode:
        raise CompositionError(process.stderr.decode("utf-8", errors="replace").strip())
    return process.stdout


def names(root: Path, *args: str) -> set[str]:
    return {name.decode("utf-8") for name in git_bytes(root, *args).split(b"\0") if name}


def destination(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    path = root.joinpath(*relative.parts)
    if relative.is_absolute() or ".." in relative.parts or not path.resolve().is_relative_to(root.resolve()):
        raise CompositionError(f"Cannot compose repository path: {name}")
    return path


def digest(path: Path) -> str | None:
    if path.is_symlink():
        raise CompositionError(f"Symbolic links are unsupported in changed paths: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise CompositionError(f"Changed path is not a regular file: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export_commit(repository: Path, sha: str, target: Path) -> None:
    entries = git_bytes(repository, "ls-tree", "-rz", sha).split(b"\0")
    with subprocess.Popen(["git", "cat-file", "--batch"], cwd=repository,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as objects:
        try:
            for entry in entries:
                if not entry:
                    continue
                metadata, raw_name = entry.split(b"\t", 1)
                mode, kind, oid = metadata.split()
                if ".irus" in PurePosixPath(raw_name.decode("utf-8")).parts:
                    continue
                if mode == b"120000":
                    continue  # The scanner also skips symlinks.
                if kind != b"blob":
                    raise CompositionError("Submodules are unsupported in combined checks")
                path = destination(target, raw_name.decode("utf-8"))
                path.parent.mkdir(parents=True, exist_ok=True)
                objects.stdin.write(oid + b"\n")
                objects.stdin.flush()
                header = objects.stdout.readline().split()
                if len(header) != 3 or header[1] != b"blob":
                    raise CompositionError("Git could not read a snapshot object")
                remaining = int(header[2])
                with path.open("wb") as output:
                    while remaining:
                        chunk = objects.stdout.read(min(remaining, 65536))
                        if not chunk:
                            raise CompositionError("Git returned an incomplete snapshot object")
                        output.write(chunk)
                        remaining -= len(chunk)
                if objects.stdout.read(1) != b"\n":
                    raise CompositionError("Git returned an invalid snapshot object")
        except BaseException:
            objects.kill()
            raise
        finally:
            objects.stdin.close()


@dataclass
class Workspace:
    root: Path
    sha: str
    worktrees: list[Path]
    sources: dict[str, list[str]]

    def apply_changes(self) -> None:
        changes: dict[str, tuple[str | None, Path]] = {}
        fingerprints = []
        for tree in self.worktrees:
            changed = names(tree, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", self.sha, "--")
            changed |= names(tree, "ls-files", "--others", "--exclude-standard", "-z")
            for name in sorted(changed):
                if ".irus" in PurePosixPath(name).parts:
                    continue
                source = destination(tree, name)
                checksum = digest(source)
                if name in changes and changes[name][0] != checksum:
                    raise CompositionError(f"Conflicting versions of {name}: {changes[name][1]} and {source}. Resolve this path before checking integration.")
                changes[name] = checksum, source
                self.sources.setdefault(name, []).append(str(source))
                fingerprints.append((source, checksum))
        for name, (checksum, source) in changes.items():
            path = destination(self.root, name)
            if checksum is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, path)
                if digest(path) != checksum:
                    raise CompositionError(f"File changed during snapshot: {source}. Retry the check.")
        if any(digest(path) != checksum for path, checksum in fingerprints):
            raise CompositionError("A source file changed during snapshot. Retry the check.")


@contextmanager
def compose(paths: list[Path]):
    trees = list(dict.fromkeys(Path(path).resolve() for path in paths))
    try:
        for tree in trees:
            if Path(git(tree, "rev-parse", "--show-toplevel")).resolve() != tree:
                raise CompositionError(f"Select a worktree root, not a subdirectory: {tree}")
        repositories = {(tree / git(tree, "rev-parse", "--git-common-dir")).resolve() for tree in trees}
        if len(repositories) != 1:
            raise CompositionError("Combined checks require worktrees of the same Git repository")
        heads = [git(tree, "rev-parse", "HEAD") for tree in trees]
        sha = git(trees[0], "merge-base", "--octopus", *heads)
        if not sha:
            raise CompositionError("Selected worktrees have no common base")
    except (GitError, OSError) as exc:
        raise CompositionError(str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="irus-combined-") as temporary:
        root = Path(temporary)
        export_commit(trees[0], sha, root)
        yield Workspace(root, sha, trees, {})
