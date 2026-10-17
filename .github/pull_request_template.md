## Summary

<!-- One sentence describing what this PR changes. -->

## Related Issue

Closes #

## Changes Made

| File | What Changed |
|------|-------------|
|      |             |

## Checklist

- [ ] An issue exists and is linked above
- [ ] Acceptance criteria from the issue are met
- [ ] `uv run ruff check --fix .` and `uv run ruff format .` pass
- [ ] `uv run pytest` passes (and `uv run python evals.py` if invitation decision logic changed)
- [ ] LinkedIn scraping selector fallback chains preserved
- [ ] Does not touch LinkedIn write actions (send/delete/archive/report/block/leave); if it does, the `linkedin_guard.py` safeguards and human-approval contract are preserved
- [ ] No unrelated changes included
