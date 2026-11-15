# Autopilot: this project runs without the owner
Owner, 2026-11-15: "ideally I personally do not want to have to do anything". One scheduled task runs the
[plan in the README](../README.md#plan); the recorder (a container) needs no Claude at all.

## The task
"Latency-arb nightly": every night 00:17 Europe/Zurich, a fresh Claude session on this server in this folder.
Id `trig_01AugRicT6gW4T18Z7azJ1a8`, first run 2026-11-15 23:17 UTC; it carries no connectors (none needed). Find or change it with the
scheduled-task tools (`list_triggers`, `update_trigger`). Its prompt only says: read
`CLAUDE.md`, the README and this file, then do "A session's job" below.

## A session's job
1. **Health, always** (2 minutes):
   - `docker ps --filter name=latency-recorder` is Up, `docker logs --tail 3 latency-recorder` shows a line from the
     last 10 minutes and no `PAUSED` (it pauses itself when the disk runs low); today's `data/ext/crypto/live/*_pmc.jsonl.gz` files grow.
   - `df -h /`: if under 7 GB free, compress old hours harder (`xz`) or delete what the replay no longer needs; never
     touch `/root/polymarket-bot`.
   - Broken? Fix it first (`docker compose up -d recorder`), and say what happened in the LOG.
2. **The next open step** of the [plan](../README.md#plan). One step per night is fine; don't rush money code.
3. **Write it down:** a dated entry in [LOG.md](LOG.md) (result first, with numbers, negative ones too), update the
   README ("Where it stands", the plan table, "Needs the owner"), commit.
4. **Tell the owner only when needed:** `sh scripts/notify.sh "title" "text"` for something only he can do, and for
   the verdict. Nothing else.
5. **Last step:** `sh scripts/end_session.sh` (a finished session otherwise keeps ~250 MB of this small server).
   Never in a session a person is using.

## Limits
- **Real money:** at most **$30 total loss**, ever, until the owner says otherwise (owner, 2026-11-15). The cap is
  enforced in the trader's code and by the wallet holding no more than that. Orders of the minimum size only.
  More money, a bigger size, or continuing after the $30 is spent: only the owner.
- **Never touch the LP bot:** not its containers, not its files, not its balance. No order may spend the LP pilot's
  money; no session moves money off any wallet. Read `/root/polymarket-bot/docs/INFRA.md#wallet` before wallet work.
- **Never tune on the forward data.** The test is fixed in the README. Other settings may be reported as extra rows,
  clearly marked, and never become the verdict.
- **Server:** no changes to the server itself (packages, users, swap, systemd). Containers get a `mem_limit`.
  One heavy job at a time, and check `free -m` first: the LP bot's lab jobs and recorder come first.
- **Claude usage:** the owner shares his Claude limits with these sessions. Scheduled sessions run at night
  (weekdays 22:00–07:00 Europe/Zurich) or at weekends, and stay short.
- No geoblock tricks, ever.

## If a task did not run
A night without a LOG entry means the task failed (usage limit, or the Claude login on the server expired; then
only the owner can log in again). The next session does the missed step and notes it.
