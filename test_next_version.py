#!/usr/bin/env python3
"""Exercises next_version.py against synthetic histories. No dependencies — run it with `python3`.

Each case builds a throwaway git repository, replays a plausible sequence of tags and Conventional Commits, and
asserts the version the policy hands back. The cases are not decorative: case 4 is the one a naive implementation
gets wrong (it computes the bump from the last TAG, so the `feat` that justified 1.1.0 falls out of the window
once 1.1.0-beta.1 is cut, and the next beta silently retargets 1.0.1).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).with_name("next_version.py").resolve()

# (name, [history: ("tag", name) | ("commit", subject)], prerelease, expected)
CASES: list[tuple[str, list[tuple[str, str]], bool, str]] = [
    ("no tags at all — pre-release", [("commit", "feat: initial")], True, "0.1.0-beta.1"),
    ("no tags at all — stable", [("commit", "feat: initial")], False, "0.1.0"),
    (
        "betas only, no stable yet — the target must not move",
        [("commit", "feat: initial"), ("tag", "v1.0.0-beta.6"), ("commit", "fix: something")],
        True,
        "1.0.0-beta.7",
    ),
    (
        # Pre-first-stable there is no released API to break, so a breaking change must NOT move the target off
        # the pending X.Y.Z — the betas ARE the run-up to it. This pins the deliberate discard of `level` in the
        # `elif highest` branch of next_version.py, so a future refactor cannot change it silently. Contrast with
        # the post-stable case below, where a breaking change legitimately retargets and restarts the counter.
        "betas only, no stable yet — a breaking change still must not move the target",
        [("commit", "feat: initial"), ("tag", "v1.0.0-beta.6"), ("commit", "feat!: breaking change")],
        True,
        "1.0.0-beta.7",
    ),
    (
        "betas only — promoting to stable",
        [("commit", "feat: initial"), ("tag", "v1.0.0-beta.6"), ("commit", "fix: something")],
        False,
        "1.0.0",
    ),
    (
        "stable + a feat — a new beta series opens",
        [("commit", "feat: initial"), ("tag", "v1.0.0"), ("commit", "feat: new thing")],
        True,
        "1.1.0-beta.1",
    ),
    (
        "mid-series: the target 1.1.0 must HOLD, not fall back to 1.0.1",
        [
            ("commit", "feat: initial"),
            ("tag", "v1.0.0"),
            ("commit", "feat: new thing"),
            ("tag", "v1.1.0-beta.1"),
            ("commit", "fix: oops"),
        ],
        True,
        "1.1.0-beta.2",
    ),
    (
        "a breaking change mid-series retargets and restarts the counter",
        [
            ("commit", "feat: initial"),
            ("tag", "v1.0.0"),
            ("commit", "feat: new thing"),
            ("tag", "v1.1.0-beta.1"),
            ("commit", "feat!: breaking change"),
        ],
        True,
        "2.0.0-beta.1",
    ),
    (
        # The promote counterpart of the case above, and the one that would hurt most if someone ever
        # "simplified" the promote into "drop the -beta suffix". Once a stable exists, the target is DERIVED from
        # the commits since that stable, never read off the highest beta: a `feat!` anywhere in the 1.1.0-beta
        # series makes the promoted stable 2.0.0, not 1.1.0. This is the whole compatibility promise of the policy.
        "promoting a beta series that contains a breaking change yields the retargeted stable, not the beta's X.Y.Z",
        [
            ("commit", "feat: initial"),
            ("tag", "v1.0.0"),
            ("commit", "feat: new thing"),
            ("tag", "v1.1.0-beta.1"),
            ("commit", "feat!: breaking change"),
        ],
        False,
        "2.0.0",
    ),
    (
        "0ver: below 1.0.0 a breaking change moves the MINOR, never to 1.0.0",
        [
            ("commit", "feat: initial"),
            ("tag", "v0.1.0"),
            ("commit", "refactor!: drop the old API\n\nBREAKING CHANGE: gone."),
        ],
        False,
        "0.2.0",
    ),
    (
        "an unconventional commit cannot claim a bump it did not declare",
        [("commit", "feat: initial"), ("tag", "v1.0.0"), ("commit", "wip whatever")],
        False,
        "1.0.1",
    ),
]


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout


def build(repo: Path, history: list[tuple[str, str]]) -> None:
    run(repo, "git", "init", "-q", "-b", "main")
    run(repo, "git", "config", "user.email", "t@t")
    run(repo, "git", "config", "user.name", "t")
    for kind, value in history:
        if kind == "commit":
            run(repo, "git", "commit", "-q", "--allow-empty", "-m", value)
        else:
            run(repo, "git", "tag", value)


def version_of(repo: Path, prerelease: bool) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "true" if prerelease else "false"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"INITIAL_VERSION": "0.1.0", "PATH": "/usr/bin:/bin"},
    )
    if out.returncode != 0:
        raise AssertionError(f"the policy refused: {out.stdout}{out.stderr}")
    for line in out.stdout.splitlines():
        if line.startswith("version="):
            return line.split("=", 1)[1]
    raise AssertionError(f"no version in output: {out.stdout!r}")


def main() -> None:
    failures = 0
    for name, history, prerelease, expected in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            build(repo, history)
            try:
                got = version_of(repo, prerelease)
            except AssertionError as exc:
                print(f"  ERROR  {name}\n         {exc}")
                failures += 1
                continue
        status = "ok  " if got == expected else "FAIL"
        if got != expected:
            failures += 1
        print(f"  {status}   {name}\n         expected {expected}, got {got}")

    # A release with nothing in it is a mistake, not a no-op — the policy must refuse rather than invent a patch.
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        build(repo, [("commit", "feat: initial"), ("tag", "v1.0.0")])
        out = subprocess.run(
            [sys.executable, str(SCRIPT), "false"], cwd=repo, capture_output=True, text=True
        )
        if out.returncode == 0:
            print("  FAIL   refuses to release when there is no commit since the last tag")
            failures += 1
        else:
            print("  ok     refuses to release when there is no commit since the last tag")

    print()
    if failures:
        sys.exit(f"{failures} failing case(s).")
    print(f"All {len(CASES) + 1} cases pass.")


if __name__ == "__main__":
    main()
