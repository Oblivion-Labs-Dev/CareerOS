# Contributing to CareerOS

Thanks for helping. CareerOS is a self-hosted tool people use for their real job search, so
reliability and safety matter more than speed.

1. Open an issue first for anything larger than a small fix, so we can agree on the approach.
2. Set up locally with `./setup.sh` (or `setup.bat` on Windows), then run `pnpm dev`.
3. Make a focused change on a branch. Read [AGENTS.md](./AGENTS.md) for the code map and the
   safety rules, which apply to people and coding agents alike.
4. Add tests. A bug fix needs a test that fails without the fix.
5. Run `cd apps/api && python -m pytest tests -m "not network"` and, for web changes, the
   typecheck in AGENTS.md. For UI changes, include a screenshot from the running app.
6. Open a pull request describing what changed, why, and how you checked it.

Never include your own resume, API keys, browser profiles or application data in a pull request.
By contributing you agree that your contribution is licensed under the [MIT License](./LICENSE).
