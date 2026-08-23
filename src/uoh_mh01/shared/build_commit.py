"""The running build's own git state — the commit that is actually playing,
and whether the tree it came from was clean.

BOOK ch.5, verified against the PDF: "בכל משחק חובה לרשום בהצהרה את מזהה
הקומיט המדויק ששוחק, כדי שהבוחן יוכל לשחזר בדיוק את הגרסה שהתמודדה" — every
game must record in its declaration the EXACT commit that played, so the
examiner can reproduce the version that competed; and §9 requires the same id
in the emailed JSON as `github_commit`. Read via `git rev-parse`, never
hand-typed, so a code change between series is picked up automatically.

WHY DIRTINESS IS PART OF THIS. A commit id declared from a tree with
uncommitted edits names a version that is NOT what ran. That is a false
declaration under App. E rules 37/38, and it is undetectable from the outside:
the examiner checks out the hash we gave, gets different behaviour, and the
disagreement looks like tampering rather than sloppiness. So the two facts are
captured together and travel together.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

GIT_TIMEOUT_SEC = 5


class DirtyWorkingTreeError(Exception):
    """A counted series was asked to start from a tree with uncommitted
    changes. Refused before the handshake, never mid-series."""


@dataclass(frozen=True)
class RepoState:
    """`commit` is None when the commit genuinely cannot be determined — no
    git, not a repository, no commits yet. NOT the string "unknown": a report
    field carrying "unknown" looks populated to every downstream check, and the
    mandatory-field warning would stop firing on a gap that is still there."""

    commit: str | None
    dirty: bool
    dirty_paths: tuple[str, ...] = ()

    @property
    def declarable(self) -> bool:
        return self.commit is not None and not self.dirty


def _git(args: list[str], cwd: str | None) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT_SEC, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Returned RAW. `.strip()` here would eat the leading status column of
    # `git status --porcelain`'s FIRST line only (` M path` -> `M path`),
    # silently truncating exactly one reported path by one character while
    # every other line stayed correct — the kind of off-by-one that reads as a
    # typo in the output rather than a bug.
    return result.stdout


def current_commit_hash(cwd: str | None = None) -> str | None:
    out = _git(["rev-parse", "HEAD"], cwd)
    return out.strip() if out is not None else None


def repo_state(cwd: str | None = None) -> RepoState:
    """The commit playing, and whether its tree was clean.

    `git status --porcelain` covers staged, unstaged and untracked changes.
    Untracked files are deliberately included: a brand-new module the
    examiner's checkout will not have is exactly as reproducibility-breaking as
    an edited one, and it is the easier of the two to leave behind by accident.
    """
    commit = current_commit_hash(cwd)
    if commit is None:
        return RepoState(commit=None, dirty=False)
    status = _git(["status", "--porcelain"], cwd)
    if status is None:
        # We have a commit but cannot judge the tree. Treated as dirty rather
        # than clean: a wrong "clean" produces a false declaration nobody can
        # see, a wrong "dirty" produces a refusal someone can read and act on.
        return RepoState(commit=commit, dirty=True, dirty_paths=("<git status unavailable>",))
    # Porcelain v1: two status columns, a space, then the path.
    paths = tuple(line[3:] for line in status.splitlines() if line.strip())
    return RepoState(commit=commit, dirty=bool(paths), dirty_paths=paths)


def assert_declarable(state: RepoState, *, counted: bool) -> list[str]:
    """Gate a series start on the repo state. Returns warnings to print.

    A COUNTED series refuses; a friendly warns. The asymmetry is the point:
    warm-ups are explicitly encouraged (book ch.9.2.1) and owe no report to
    anyone, so a dirty tree costs nothing there — while a counted series is
    exactly where an unreproducible commit id becomes a rules-37/38 problem.
    """
    if state.declarable:
        return []
    if state.commit is None:
        reason = "the git commit could not be determined (no git, or not a repository)"
    else:
        shown = ", ".join(state.dirty_paths[:5]) + (" ..." if len(state.dirty_paths) > 5 else "")
        reason = f"the working tree has uncommitted changes: {shown}"
    if counted:
        raise DirtyWorkingTreeError(
            f"refusing to start a COUNTED series: {reason}. The step-0 declaration must name the exact "
            "commit that played (book ch.5) and the emailed report carries it as `github_commit` "
            "(section 9); declaring a commit that is not what ran is a false declaration under App. E "
            "rules 37/38. Commit or stash, then start again."
        )
    return [f"WARNING: {reason}. This is fine for a friendly, but a counted series will refuse to start."]
