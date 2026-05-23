## Summary

<!-- What changed and why. One paragraph max. Link issues with "Closes #". -->

Closes #

## Scope

<!-- Check ALL areas this PR touches. Reviewers and CI use this to gauge blast radius. -->

- [ ] `secapi_client/` — Public SDK package
- [ ] `omni_datastream_py/` — Legacy / aliased package
- [ ] `tests/` — Test suite
- [ ] `examples/` — Example scripts
- [ ] `pyproject.toml` — Packaging, deps, tooling config
- [ ] `README.md` / docs
- [ ] `.github/` — CI/CD workflows

## Changes

<!-- Bullet points grouped by area. Be specific — diffs are for code, this is for intent. -->

-
-

## Verification

<!-- What you ran locally. Paste actual commands and their outcomes. -->

```bash
uv sync                  # ✅ / ❌
uv run pytest            # ✅ / ❌
uv run ruff check .      # ✅ / ❌
uv run mypy secapi_client  # ✅ / ❌
```

<details>
<summary>Additional verification (expand if applicable)</summary>

```bash
# Build a wheel
uv build

# Live smoke
SECAPI_API_KEY=... uv run python examples/<example>.py

# Format check
uv run ruff format --check .
```

</details>

## Deployment Impact

<!-- Skip this section entirely for code-only changes with no release impact. -->

- [ ] New version bump in `pyproject.toml`
- [ ] Breaking API change (semver major)
- [ ] PyPI publish required
- [ ] Docs (README / examples) updated to match
- [ ] Companion docs PR in org docs site

## Completion Attestation

<!-- You MUST select one. This is a binding statement of delivery status. -->

- [ ] **100% complete, 100% functional.** All code is written, tested, type-checked, and works end-to-end against live SEC API. No outstanding work remains.
- [ ] **Not fully complete or functional.** Deltas listed below.

### Deltas (only if attesting incomplete)

<!-- Short bullets. Items intentionally deferred from this PR's stated scope. -->

-

## Screenshots / Demo

<!-- Terminal output, CLI snippets, or API response examples. Delete section if not applicable. -->

---

<details>
<summary>Agent Context</summary>

<!-- This section is for AI coding agents that may continue or review this work.
     Fill in what's relevant; delete what isn't. -->

**Key files to read first:**
<!-- List the 3-5 most important files for understanding this PR's changes. -->
- `secapi_client/__init__.py`
-

**Decisions made:**
<!-- Non-obvious choices and why. Agents should not re-litigate these. -->
-

**Relevant docs:**
- `README.md`
- https://docs.secapi.ai

**Conventions applied:**
<!-- Pythonic conventions, typing, dataclass vs pydantic, error handling, response metadata. -->
-

</details>
