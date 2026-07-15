#!/usr/bin/env python3
"""Compute the next release version from Conventional Commits.

Usage:  next_version.py <true|false>        # true = cut a pre-release
Emits:  version=X.Y.Z[-beta.N] / level=<major|minor|patch> / base=<tag|ROOT> on stdout, as KEY=VALUE lines.

THE ONE RULE WORTH KNOWING: the target X.Y.Z is computed from the commits since the last STABLE release, never
since the last tag. Counting from the last tag would drop the `feat` that justified 1.1.0 out of the window as
soon as 1.1.0-beta.1 was cut, and the next beta would silently retarget 1.0.1. Counting from the last stable
keeps the target fixed across a beta series — and lets a breaking change that lands mid-series legitimately
push the target to 2.0.0, restarting the beta counter.

Below 1.0.0, a breaking change bumps the MINOR (0ver): 0.x is unstable by definition, and promoting it to 1.0.0
is a product decision, not something a commit message gets to make.

WHY THIS IS NOT git-cliff --bumped-version, WHICH IS ALREADY IN THE STACK.

Measured against git-cliff 2.11.0, not assumed. It gets the hard case RIGHT — a `fix` landing during a
1.1.0-beta series correctly yields 1.1.0-beta.2, holding the target rather than regressing to 1.0.1. It fails on
two others, and both are fatal here:

  1. THERE IS NO BETA/STABLE CHOICE. git-cliff has no such flag; the outcome is dictated entirely by the last
     tag. Last tag stable  -> it produces a stable, so a beta series can never be OPENED (v1.0.0 + feat gives
     v1.1.0, never 1.1.0-beta.1). Last tag a beta -> it continues the series, so a beta series can never be
     PROMOTED (v1.0.0-beta.6 gives v1.0.0-beta.7, never 1.0.0). Releases here are a dispatch-time choice; that
     model is simply not expressible.

  2. A BREAKING CHANGE MID-SERIES IS SWALLOWED. `feat!:` landing during a 1.1.0-beta series still yields
     1.1.0-beta.2 — even with `breaking_always_bump_major = true` in [bump]. The eventual 1.1.0 would ship a
     breaking change against 1.0.0. On a parent POM that pins every client in the fleet, that is a correctness
     bug, not a preference.

semantic-release is correct on all of it, but only through a BRANCH-based prerelease model (a `beta` branch
alongside `main`). Adopting it means restructuring how releases are cut — plus a Node runtime and its plugins in
a job holding `contents: write`, with @semantic-release/git (commit back to main) disabled, because the org
ruleset forbids exactly that. See the memory note "ci-n-ecrit-pas-sur-main".

So this file is not custom tooling for its own sake: it is a POLICY no off-the-shelf tool implements. The
alternative is not "use a standard tool", it is "adopt a different release model". test_next_version.py is what
keeps the policy honest — change one, change the other.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

INITIAL_VERSION = os.environ.get("INITIAL_VERSION", "0.1.0")
PRE_ID = "beta"

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-" + PRE_ID + r"\.(\d+))?$")
# Conventional Commits: type(optional scope)!: subject
SUBJECT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]*\))?(?P<bang>!)?:\s")
BREAKING_RE = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)


def git(*args: str) -> str:
    return subprocess.run(("git",) + args, capture_output=True, text=True, check=True).stdout.strip()


def parse_tags() -> list[tuple[tuple[int, int, int, int], str]]:
    """Every release tag, as (sort_key, name). A pre-release sorts BEFORE its stable: 1.0.0-beta.6 < 1.0.0."""
    out = []
    for name in git("tag", "--list", "v[0-9]*").splitlines():
        m = TAG_RE.match(name.strip())
        if not m:
            continue
        major, minor, patch = (int(m.group(i)) for i in (1, 2, 3))
        pre = m.group(4)
        # A stable release sorts above every pre-release of the same X.Y.Z, hence the sentinel.
        rank = int(pre) if pre is not None else sys.maxsize
        out.append(((major, minor, patch, rank), name.strip()))
    return sorted(out)


def bump_level(base_ref: str) -> str:
    """The strongest bump the commits since base_ref call for."""
    rng = f"{base_ref}..HEAD" if base_ref else "HEAD"
    # %x00 between records: a commit body may contain anything, including blank lines.
    raw = git("log", rng, "--format=%B%x00")
    messages = [m.strip() for m in raw.split("\x00") if m.strip()]
    if not messages:
        sys.exit(f"::error::No commits since {base_ref or 'the root'} — there is nothing to release.")

    level = "patch"
    for msg in messages:
        subject = msg.splitlines()[0]
        m = SUBJECT_RE.match(subject)
        if not m:
            continue  # unconventional commit: it cannot claim a bump it did not declare
        if m.group("bang") or BREAKING_RE.search(msg):
            return "major"
        if m.group("type") == "feat":
            level = "minor"
    return level


def apply_bump(version: tuple[int, int, int], level: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if level == "major":
        # 0ver: below 1.0.0 a breaking change moves the minor. See the module docstring.
        return (0, minor + 1, 0) if major == 0 else (major + 1, 0, 0)
    if level == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("true", "false"):
        sys.exit("usage: next_version.py <true|false>")
    prerelease = sys.argv[1] == "true"

    tags = parse_tags()
    stables = [t for t in tags if t[0][3] == sys.maxsize]
    latest_stable = stables[-1] if stables else None
    highest = tags[-1] if tags else None

    if latest_stable:
        base_tag = latest_stable[1]
        level = bump_level(base_tag)
        target = apply_bump(latest_stable[0][:3], level)
    elif highest:
        # Pre-1.0 of anything: the existing betas ARE the run-up to that X.Y.Z. It is the target, not something
        # to bump away from — otherwise a feat between two betas would retarget the release nobody asked to move.
        base_tag = ""
        level = bump_level(highest[1])
        target = highest[0][:3]
    else:
        base_tag = ""
        level = bump_level("")
        target = tuple(int(p) for p in INITIAL_VERSION.split("."))  # type: ignore[assignment]

    xyz = "{}.{}.{}".format(*target)

    if prerelease:
        n = 1
        if highest and highest[0][3] != sys.maxsize and highest[0][:3] == target:
            n = highest[0][3] + 1
        version = f"{xyz}-{PRE_ID}.{n}"
    else:
        version = xyz

    print(f"version={version}")
    print(f"level={level}")
    print(f"base={base_tag or 'ROOT'}")


if __name__ == "__main__":
    main()
