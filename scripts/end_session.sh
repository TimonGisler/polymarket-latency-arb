#!/bin/sh
# Last step of an unattended autopilot session: end its own Claude process, which would otherwise hold ~250 MB
# (docs/AUTOPILOT.md; copied from polymarket-bot). Never for a session a person is using. --dry only prints the PID.
pid=$$
while [ "$pid" -gt 1 ]; do
  pid=$(ps -o ppid= -p "$pid" | tr -d ' ')
  if readlink "/proc/$pid/exe" | grep -q '/claude/versions/'; then   # the program itself: a shell's text may mention it
    [ "$1" = "--dry" ] && { echo "$pid"; exit 0; }
    exec kill "$pid"
  fi
done
echo "no Claude ancestor found: nothing done" >&2
exit 1
