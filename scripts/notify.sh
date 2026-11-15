#!/bin/sh
# Phone push to the owner (ntfy.sh), same topic as the LP bot's monitor: NTFY_TOPIC in /root/polymarket-bot/.env.
# Only for what needs the owner or the weekly verdict. Usage: sh scripts/notify.sh "ASCII title" "text"
topic=$(grep '^NTFY_TOPIC=' /root/polymarket-bot/.env | cut -d= -f2-)
[ -n "$topic" ] || { echo "no NTFY_TOPIC" >&2; exit 1; }
curl -sS -m 15 -H "Title: $1" -d "$2" "https://ntfy.sh/$topic" >/dev/null && echo sent
