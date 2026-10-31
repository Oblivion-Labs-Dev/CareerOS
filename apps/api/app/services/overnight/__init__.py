"""Overnight operating system: two independent loops around the Auto Apply worker.

Loop A (`supervisor`) is deterministic and cheap: every 30 minutes it observes the
worker, the run and the queue through the normal API, and resumes recoverable
work. It never restarts a live application, never runs a second worker and never
touches the live-apply gates.

Loop B (`improver`) works between those checks, one bounded improvement at a
time: it groups stuck applications by shared root cause, asks a headless coding
agent for one focused fix in a separate git worktree, validates it with tests
and review, and leaves it *awaiting promotion*. A validated fix reaches the live
worker only through `promotion`, which requires the worker to be idle and the
production security gates to pass, and requeues the group only after that.

Shared state lives in `data/overnight/` (see `state.py`). Docs:
`docs/overnight-loops.md`.
"""
