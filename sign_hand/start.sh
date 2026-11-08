#!/bin/bash
# One command to start everything for the Rob demo:
#   1) opens the cloudflared tunnel (background) and finds its public URL
#   2) fills that URL into GROK_PROMPT.txt and copies the prompt to the clipboard
#   3) runs rob.py, the launcher Grok talks to; it boots the Rob app (coach.py) and can
#      stop / restart it when Grok asks
# Usage:  bash sign_hand/start.sh            (ESP32 plugged in)
#         bash sign_hand/start.sh --dry      (no ESP32)
#         bash sign_hand/start.sh --dry --camera 1   (pick a camera by number; default = built-in Mac camera)
# Stop with Ctrl+C (also closes the tunnel). A restart gives a NEW URL: paste the new prompt into Grok.
cd "$(dirname "$0")"
LOG=/tmp/rob_tunnel.log
: > "$LOG"
cloudflared tunnel --region us --url http://localhost:5050 > "$LOG" 2>&1 &
TUNNEL_PID=$!
trap 'kill $TUNNEL_PID 2>/dev/null' EXIT

echo "Starting tunnel..."
URL=""
for i in $(seq 1 30); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" | head -1)
  [ -n "$URL" ] && break
  sleep 1
done
if [ -z "$URL" ]; then
  echo "!! Tunnel did not start. See $LOG"; exit 1
fi

sed "s#<TUNNEL_URL>#$URL#g" GROK_PROMPT.txt > /tmp/rob_prompt.txt
pbcopy < /tmp/rob_prompt.txt
echo
echo "============================================================"
echo " Tunnel URL:  $URL"
echo " The Grok prompt (with this URL) is now on your CLIPBOARD."
echo " -> In Grok Bot: paste it (Cmd+V) and send, then start live voice."
echo "============================================================"
echo

python3 rob.py "$@"
