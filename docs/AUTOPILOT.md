# Autopilot: this project runs without the owner
Owner, 2026-11-15: "ideally I personally do not want to have to do anything". One scheduled task runs the
[plan in the README](../README.md#plan); the recorder (a container) needs no Claude at all.

## The task
"Latency-arb nightly": every night 00:17 Europe/Zurich, a fresh Claude session on this server in this folder.
Id `trig_01AugRicT6gW4T18Z7azJ1a8`, first run 2026-11-15 23:17 UTC, model `claude-opus-5-5` (owner: at least Opus);
it carries no connectors (none needed).

"Latency-arb verdict": one-off, **Sunday 2026-11-22 08:30 Europe/Zurich** (`trig_01Rd1ZtaAekhRzbUaHwuLqLG`, Opus). It
does plan step 6 and pushes the verdict to the owner's phone. Owner, 2026-11-15: the verdict must be on his phone by
Sunday 11-22 around 12:00 Zurich at the latest, so he has the weekend to work on it. The nightly run at 00:17 that
Sunday prepares everything (the replay on all days ready to run), so the verdict session only runs and writes it. Find or change it with the
scheduled-task tools (`list_triggers`, `update_trigger`). Its prompt only says: read
`CLAUDE.md`, the README and this file, then do "A session's job" below.

## A session's job
1. **Health, always** (2 minutes):
   - `docker ps --filter name=latency-recorder` is Up, `docker logs --tail 3 latency-recorder` shows a line from the
     last 10 minutes and no `PAUSED` (it pauses itself when the disk runs low); today's `data/ext/crypto/live/*_pmc.jsonl.gz` files grow, and in the log's 5-minute lines every counter rises, `cl` (Chainlink) too.
   - `latency-trader` is Up and `data/trader/summary.json` was updated in the last minute. The recorder restarting
     itself about once a day (log line `memory ... clean exit`) is expected (LOG 2026-11-17).
   - Real orders (since 2026-11-18): in `summary.json`, "real net loss vs cap" stays under 30 and "wallet cash" matches
     roughly $30 − loss. Compare real with paper on the same order ids in `decisions.jsonl` (`ev` "order" vs the
     5-share fill of `ev` "exec"): fill rate and price; that comparison is half of the verdict. The trader itself
     stops ordering at the cap; never raise it.
   - After any recorder restart or crash: `python3 scripts/fix_gz.py` once the hour has ended (a kill leaves hour files that normal readers can only read in part).
   - `df -h /`: if under 7 GB free, compress old hours harder (`xz`) or delete what the replay no longer needs; never
     touch `/root/polymarket-bot`.
   - Broken? Fix it first (`docker compose up -d recorder`), and say what happened in the LOG.
2. **Replay the finished days**, every night: `docker run --rm -m 1g --cpus 1 -v $PWD:/app -w /app pmbot python -u
   research/crypto_updown/live_replay.py` (no arguments: only days not yet replayed whole, ~10 min each, then the report
   over all of them into `research/crypto_updown/out/live_replay.json`). Check `free -m` first. Read the TEST row only;
   never change the test because of it.
3. **The next open step** of the [plan](../README.md#plan). One step per night is fine; don't rush money code.
4. **Write it down:** a dated entry in [LOG.md](LOG.md) (result first, with numbers, negative ones too), update the
   README ("Where it stands", the plan table, "Needs the owner"), commit and `git push`. The owner reads the status page (`dashboard.py`), which shows those README sections and the newest
   LOG entry, so keep them short and current; the trader writes `data/trader/summary.json` for it.
5. **Tell the owner only when needed:** `sh scripts/notify.sh "title" "text"` for something only he can do, and for
   the verdict. Nothing else.
6. **Last step:** `sh scripts/end_session.sh` (a finished session otherwise keeps ~250 MB of this small server).
   Never in a session a person is using.

## Limits
- **Real money:** at most **$30 total loss**, ever, until the owner says otherwise (owner, 2026-11-15). The cap is
  enforced in the trader's code and by the wallet holding no more than that. Orders of the minimum size only.
  More money, a bigger size, or continuing after the $30 is spent: only the owner.
- **Wallet:** only the one in `.env.wallet` of this repo (README "Needs the owner"). Never print the key, never copy it,
  load it only into the container that trades or checks. The key was pasted in a chat once: no more money on it than the $30.
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
