"""
MakeCU sign-language hand — laptop bridge.

Grok Bot  --HTTPS-->  cloudflared tunnel  -->  this server (port 5050)  --USB serial-->  ESP32

Accepts loose JSON from Grok (live voice improvises), e.g.
  {"word": "FOOD"}   {"sign": "food"}   {"text": "code"}   {"ily": true}   {"word": "I love you"}
Keeps only letters the hand can form, then sends ONE line to the ESP32:
  SPELL FOOD      or      ILY

Run:   python3 sign_hand/bridge.py            (auto-finds the ESP32 USB port)
       python3 sign_hand/bridge.py --dry      (no ESP32: just prints what it would send)
       python3 sign_hand/bridge.py --port /dev/cu.usbserial-0001
"""
import glob
import re
import sys
import time

from flask import Flask, request

ALLOWED = set("ABCDEFILOUWYX")          # letters the hand can physically form
PORT_HTTP = 5050
BAUD = 115200

app = Flask(__name__)
ser = None
DRY = "--dry" in sys.argv


def find_port():
    if "--port" in sys.argv:
        return sys.argv[sys.argv.index("--port") + 1]
    for pat in ("/dev/cu.usbserial*", "/dev/cu.SLAB_USBtoUART*", "/dev/cu.wchusbserial*", "/dev/cu.usbmodem*"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def extract_text(d):
    """Pull the requested word out of whatever shape Grok sent."""
    if not isinstance(d, dict):
        return str(d or "")
    if d.get("ily") in (True, "true", "yes", 1):
        return "I LOVE YOU"
    for key in ("word", "sign", "text", "letters", "spell", "message"):
        v = d.get(key)
        if isinstance(v, list):
            return "".join(str(x) for x in v)
        if v:
            return str(v)
    return ""


def to_command(raw):
    t = raw.upper().strip()
    if re.sub(r"[^A-Z]", "", t) in ("ILOVEYOU", "ILY", "LOVEYOU"):
        return "ILY", "I-love-you handshape", ""
    letters = "".join(c for c in t if c in ALLOWED)
    skipped = "".join(sorted(set(c for c in t if c.isalpha() and c not in ALLOWED)))
    if not letters:
        return None, "", skipped
    return f"SPELL {letters}", letters, skipped


def send(line):
    print(f"--> ESP32: {line}", flush=True)
    if DRY or ser is None:
        return
    ser.write((line + "\n").encode())
    ser.flush()


@app.get("/")
def health():
    return {"ok": True, "esp32": "dry-run" if DRY else (ser.port if ser else "NOT CONNECTED"),
            "allowed_letters": "".join(sorted(ALLOWED))}


@app.post("/sign")
def sign():
    d = request.get_json(silent=True)
    if d is None:                         # Grok sometimes sends plain text
        d = {"text": request.get_data(as_text=True)}
    print(f"GOT: {d}", flush=True)
    # Teaching: {"letter":"D"} -> hold that one shape until the next command
    if isinstance(d, dict) and d.get("letter"):
        t = str(d["letter"]).upper().strip()
        if re.sub(r"[^A-Z]", "", t) in ("ILY", "ILOVEYOU"):
            send("ILYHOLD")
            return {"ok": True, "showing": "I-love-you"}
        c = next((ch for ch in t if ch.isalpha()), "")
        if c in ALLOWED:
            send(f"SHOW {c}")
            return {"ok": True, "showing": c}
        return {"ok": False, "showing": "", "error": f"the hand cannot form {c or t}; explain it in words only"}
    raw = extract_text(d)
    cmd, signed, skipped = to_command(raw)
    if not cmd:
        return {"ok": False, "signed": "", "skipped": skipped,
                "error": "no signable letters; use only " + "".join(sorted(ALLOWED))}, 200
    send(cmd)
    return {"ok": True, "signed": signed, "skipped": skipped}


@app.post("/open")
def open_hand():
    send("OPEN")
    return {"ok": True}


if __name__ == "__main__":
    if not DRY:
        port = find_port()
        if not port:
            print("!! No ESP32 USB port found. Plug it in, or run with --dry to test without it.")
            sys.exit(1)
        import serial                      # pip3 install pyserial
        ser = serial.Serial(port, BAUD, timeout=1)
        time.sleep(2)                      # ESP32 resets when the port opens
        print(f"Connected to ESP32 on {port}")
    else:
        print("DRY RUN: no ESP32, commands are only printed")
    app.run(port=PORT_HTTP)
