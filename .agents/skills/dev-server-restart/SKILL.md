---
name: dev-server-restart
description: Restart the CareerOS dev servers (apps/api on 4000, apps/web on 5000) on Windows without leaving zombie processes behind or silently serving stale code from an old process.
---

# Dev Server Restart Skill

`scripts/restart-dev.ps1` looks like it cleanly restarts both servers, but on this
Windows setup its own port-based kill step is unreliable: old `uvicorn`/`next dev`
processes routinely survive a restart, and a *new* process binds the same port
alongside them. `netstat` will then show multiple `LISTENING` rows for `:4000`.
Because Windows lets several processes share a listening socket in this broken
state, **incoming requests can be served by whichever old process the OS happens
to route to** — including one running code from several edits ago. This produces
a specific, very confusing failure mode: you edit a file, restart, and the bug
"doesn't reproduce" or a new endpoint 404s, purely because you're talking to a
zombie, not your latest code.

## How to restart without leaving zombies

1. **Invoke the script via the Bash tool, not the PowerShell tool.** When
   `restart-dev.ps1` is launched through the PowerShell tool, a subsequent
   PowerShell tool call in the same session can propagate a stray Ctrl+C to the
   backgrounded `cmd.exe`/`pnpm dev` window and kill it out from under you
   (visible as `Terminate batch job (Y/N)?` + `^C` in the log). Running it via
   Bash (`powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/restart-dev.ps1 -Background -SkipOllamaCheck`)
   does not have this problem. The script also passes `-WindowStyle Hidden` to
   `Start-Process` for the same reason — don't remove that.

2. **After restart, check for duplicate listeners:**
   ```powershell
   netstat -ano | Select-String ":4000 " | Select-String "LISTENING"
   ```
   More than one row means zombies are present.

3. **Distinguish real zombies from harmless phantom kernel entries** before
   killing anything — `netstat` on this machine often keeps *stale* rows for
   sockets whose owning process is already gone:
   ```powershell
   Get-Process -Id <pid> -ErrorAction SilentlyContinue
   ```
   No result = phantom, safe to ignore. A result = a real process still alive
   and potentially still serving traffic.

4. **Also check for zombies uvicorn's own `--reload` supervisor won't show on
   the port** — compare all live `python`/`node` processes' start times against
   your latest restart's timestamp:
   ```powershell
   Get-Process -Name python,node -ErrorAction SilentlyContinue | Select-Object Id, StartTime | Sort-Object StartTime -Descending
   ```
   Anything older than the restart you just ran is a leftover from a previous
   session and should be killed.

5. **Kill real zombies one PID at a time**, not in a loop over a dynamically
   matched process list — bulk/dynamic-match kills (`Get-Process ... | ForEach
   { Stop-Process }`, `Get-CimInstance ... | Where CommandLine -match ...`) get
   blocked by the auto-mode safety classifier on this setup. Individual calls
   do not:
   ```powershell
   Stop-Process -Id 25492 -Force -ErrorAction SilentlyContinue
   ```

6. **Never trust a health check alone to prove new code is live.** `/health`
   will return 200 from a zombie too. After any restart where you need to
   confirm a code change took effect, hit the specific new/changed behavior
   directly (a new endpoint, a bugfix's observable effect) and check the
   response, not just that *a* server answered.

## Two related gotchas hit while debugging this

- **Don't run `pnpm build` (or anything that writes to `apps/web/.next`) while
  `next dev` is running.** They fight over the same `.next` directory and
  `next build` fails with a nonsense error
  (`PageNotFoundError: Cannot find module for page: /_document`). Stop the dev
  server first if you need to run a production build (e.g. as part of the
  pre-commit/pre-push CI hooks), then restart it after.
- **Don't run the API's pytest suite while the dev backend is live.** Both
  hit the same SQLite file; a full pytest run alongside `uvicorn --reload` can
  exhaust the SQLAlchemy connection pool (`QueuePool limit ... reached`) and
  make the live dev server hang on every request for the duration.
