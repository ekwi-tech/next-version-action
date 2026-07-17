# next-version-action

Derive the next release version from **Conventional Commits since the last stable tag**, as a single reusable
step. This is ekwi's version policy, extracted from the copies that were living in `ekwi-sync-skeleton` (root and
client payload) and `ekwi-sync-common` so they cannot drift — and, more importantly, so the **test** lives once
instead of being dropped from half the copies.

The policy itself is documented at the top of [`next_version.py`](./next_version.py). In one line: the target
`X.Y.Z` is computed from the commits since the last **stable** release, never the last tag, so a beta series
holds its target and a breaking change mid-series legitimately retargets it.

---

## ⚠ Prerequisite — this is a PRIVATE action

To `uses:` a private action from another private repository in the same organisation, the org must allow it:

> **`next-version-action` → Settings → Actions → General → Access →
> "Accessible from repositories in the `ekwi-tech` organization".**

Without it, every `uses: ekwi-tech/next-version-action@…` fails with `repository not found` — the same silent,
hard-to-place failure mode as installing a GitHub App on *selected* rather than *all* repositories. It is a
one-time org setting; there is nothing in the consuming repo that can reveal it is missing.

---

## Usage

```yaml
# The action reads EVERY tag and the FULL commit history. A shallow checkout is refused loudly.
- uses: actions/checkout@v7          # pin by SHA in real workflows
  with:
    fetch-depth: 0                   # REQUIRED — the whole contract

- uses: ekwi-tech/next-version-action@<sha>   # pin by SHA; Dependabot bumps it
  id: version
  with:
    prerelease: ${{ inputs.prerelease }}       # true → X.Y.Z-beta.N, false → X.Y.Z

- run: echo "Releasing v${{ steps.version.outputs.version }}"
```

### Inputs

| Input | Required | Default | Meaning |
|---|---|---|---|
| `prerelease` | yes | — | `true` cuts a pre-release (`X.Y.Z-beta.N`); `false` a stable `X.Y.Z`. |
| `initial-version` | no | `0.1.0` | The version emitted for the very first release, when no tag exists yet. |

### Outputs

| Output | Meaning |
|---|---|
| `version` | The computed version, **without** a leading `v` (e.g. `1.2.0`, `1.2.0-beta.3`). |
| `level` | The strongest bump the commits call for: `major`, `minor` or `patch`. |
| `base` | The tag the bump was computed from, or `ROOT` when no stable tag exists yet. |

The action **fails** (non-zero) when there is nothing to release — no commit since the base — rather than
inventing a patch bump. The one exception is **promoting a terminal pre-release to its stable** (`prerelease:
false` over the last `X.Y.Z-beta.N`): dropping the `-beta` suffix is a state transition, not an empty release,
so it succeeds with no fresh commit.

---

## Pinning and rollout

Pin by **commit SHA**, not `@main` or a moving major tag. A change to the policy is published as a new release;
each consumer adopts it through a **Dependabot** PR, whose CI proves the bump — the same controlled rollout the
rest of the ecosystem uses. A floating `@main` would push a policy change to every repo at once, with no gate.

## Requirements

- `python3` on the runner — present on all GitHub-hosted runners. The script is standard-library only.
- `fetch-depth: 0` on the checkout — the action asserts it and fails on a shallow clone.

## Developing this action

- **`next_version.py`** — the policy. Its module docstring is the specification.
- **`test_next_version.py`** — the policy's tests. `python3 test_next_version.py`. Change one, change the other.
- **`action.yml`** — the composite wrapper (shallow guard + invocation + output plumbing).
- CI runs the unit tests **and** a self-test that exercises the composite end to end (`.github/workflows/ci.yml`).
- Releases are cut from *Actions → Release*; the workflow **dogfoods** the action to version itself. The version
  is derived, so you choose only beta-or-latest — see [`next_version.py`](./next_version.py).
- **`.github/dependabot.yml`** / **`.github/CODEOWNERS`** — monthly SHA-pin bumps owned by ekwi-bot, reviews
  routed to the code owner. `release-notes-action` is repinned by hand, not by Dependabot.
