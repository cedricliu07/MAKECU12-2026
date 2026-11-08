#!/usr/bin/env python3
"""
Rob launcher: the always-on front door that Grok talks to (port 5050, behind the tunnel).

Grok can do everything through it:
  /start  /stop  /restart   boot or stop the Rob app (coach.py: camera window + robot)
  /status /logs             is it running, is the robot connected, what went wrong
  /help                     the full command menu (Grok can read it when unsure)
  anything else             forwarded to the running app (/teach/D, /check, /quiz ...)
                            if the app isn't running, it is started first, automatically.

Safety: only this fixed menu. Nothing from a request is ever run as a shell command.
"""
import argparse, json, os, re, subprocess, sys, threading, time, urllib.error, urllib.request

from flask import Flask, Response, request

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PORT = 5051
LOG = os.path.join(HERE, ".rob_app.log")

app = Flask(__name__)
lock = threading.Lock()
proc = None                       # running coach.py
current = {}                      # options it was started with
DEFAULTS = {"robot": "ble", "camera": None, "sim": False, "contacts": True}

HELP = {
    "system": {
        "/start": "Boot the Rob app (camera window + robot). Options: ?robot=ble|usb|dry &camera=0 &sim=1",
        "/stop": "Close the Rob app.",
        "/restart": "Restart it (same options as /start). Use when the robot or camera is stuck.",
        "/status": "Is the app running, robot connected, camera on, hand visible.",
        "/logs": "Last lines of the app log, to explain a problem.",
    },
    "teaching": {
        "/teach/D": "Robot forms a letter and holds it; reply has the sentence to say.",
        "/next": "Next letter in the lesson path.",
        "/check": "Camera verdict for the current letter + the one fix.",
        "/see": "What letter the learner's hand looks like.",
        "/hint": "Live fix + common mistake + memory tip.",
        "/practice/FOOD": "Learner signs a word letter by letter (auto-advances).",
        "/spell/FOOD": "Robot spells a word.",
        "/quiz": "Robot signs a hidden letter; then /guess/L with the learner's answer.",
        "/memory": "Learner signs from memory, robot hidden (or /memory/B).",
        "/progress": "Letters passed and best streak.",
        "/ily": "I love you.",
        "/free": "Free mode: relax the hand; learner signs anything, /see reads it.",
    },
    "robot": {
        "/raw/90,90,90,90,90": "Set servo angles directly (thumb..pinky), for calibration. /raw/off ends it.",
    },
}


def say(text, ok=True, **kw):
    return {"ok": ok, "say": text, **kw}


def running():
    return proc is not None and proc.poll() is None


def grok_header():
    """Pass the tunnel marker through, so the app knows the call came from Grok."""
    try:
        ray = request.headers.get("Cf-Ray")
    except RuntimeError:
        ray = None
    return {"Cf-Ray": ray} if ray else {}


def app_get(path, timeout=3.0):
    req = urllib.request.Request(f"http://127.0.0.1:{APP_PORT}{path}", headers=grok_header())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), r.headers.get("Content-Type", "application/json")


def start_app(opts):
    """Start coach.py with the given options and wait until it answers (max ~20 s)."""
    global proc, current
    with lock:
        if running():
            return True, "already running"
        args = [sys.executable, os.path.join(HERE, "coach.py"), "--http-port", str(APP_PORT)]
        robot = opts["robot"]
        if robot == "ble":
            args.append("--ble")
        elif robot == "dry":
            args.append("--dry")
        if opts.get("camera") is not None:
            args += ["--camera", str(int(opts["camera"]))]
        if opts.get("sim"):
            args.append("--sim")
        if not opts.get("contacts", True):
            args.append("--no-contacts")
        log = open(LOG, "w")
        proc = subprocess.Popen(args, cwd=HERE, stdout=log, stderr=subprocess.STDOUT)
        current = dict(opts)
        print(f"[launcher] started app: robot={robot} camera={opts.get('camera')} sim={opts.get('sim')}", flush=True)
    for _ in range(80):
        time.sleep(0.25)
        if not running():
            return False, "the app exited while starting: " + last_problem()
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{APP_PORT}/status", timeout=1)
            return True, "started"
        except Exception:
            pass
    return False, "the app did not answer within 20 seconds"


def stop_app():
    global proc
    with lock:
        if not running():
            proc = None
            return False
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc = None
        return True


def log_tail(n=25):
    try:
        with open(LOG, errors="replace") as f:
            lines = [l.rstrip() for l in f if l.strip()]
    except FileNotFoundError:
        return []
    noise = re.compile(r"^(I0000|W0000|INFO:|WARNING: All log|\s*\* )")
    return [re.sub(r"/Users/[^/\s]+", "~", l) for l in lines if not noise.match(l)][-n:]


def last_problem():
    for l in reversed(log_tail(60)):
        if any(k in l for k in ("!!", "Error", "error", "not found", "Traceback", "lost")):
            return l.strip()
    return "no errors in the log"


def opts_from_query():
    o = dict(current or DEFAULTS)
    q = request.args
    if q.get("robot") in ("ble", "usb", "dry"):
        o["robot"] = q["robot"]
    if q.get("camera", "").isdigit():
        o["camera"] = int(q["camera"])
    if "sim" in q:
        o["sim"] = q.get("sim") in ("1", "true", "yes")
    if "contacts" in q:
        o["contacts"] = q.get("contacts") not in ("0", "false", "no")
    return o


@app.get("/start")
def r_start():
    ok, why = start_app(opts_from_query())
    if ok:
        return say("Rob is ready. The camera window is open." if why == "started" else "Rob is already running.",
                   robot=current.get("robot"))
    return say(f"Rob didn't start: {why}", ok=False)


@app.get("/stop")
def r_stop():
    return say("Rob is closed." if stop_app() else "Rob wasn't running.")


@app.get("/restart")
def r_restart():
    o = opts_from_query()
    stop_app()
    time.sleep(0.5)
    ok, why = start_app(o)
    return say("Restarted. Rob is ready." if ok else f"Restart failed: {why}", ok=ok, robot=o["robot"])


@app.get("/status")
def r_status():
    if not running():
        return say("Rob is not running. Call /start.", ok=True, running=False)
    try:
        _, body, _ = app_get("/status")
        st = json.loads(body)
    except Exception:
        return say("Rob is starting up.", running=True)
    robot = st.get("robot", "")
    parts = [(robot if robot.lower().startswith("robot") else f"Robot: {robot}") + ".", "Camera on." if st.get("camera_on") else "Camera off.",
             "I can see a hand." if st.get("hand_visible") else "No hand in view."]
    if "searching" in robot or "not connected" in robot.lower():
        parts.append("Problem: " + last_problem())
    return say(" ".join(parts), running=True, robot=robot, options=current)


@app.get("/logs")
def r_logs():
    lines = log_tail(15)
    return {"ok": True, "running": running(), "say": "Last problem: " + last_problem(), "lines": lines}


@app.get("/help")
@app.get("/")
def r_help():
    return {"ok": True, "say": "Here is everything I can do.", "commands": HELP,
            "running": running()}


@app.route("/<path:path>", methods=["GET", "POST"])
def forward(path):
    """Everything else goes to the Rob app. Boots it first if needed."""
    if not running():
        ok, why = start_app(dict(current or DEFAULTS))
        if not ok:
            return say(f"I couldn't start Rob: {why}", ok=False), 503
    qs = ("?" + request.query_string.decode()) if request.query_string else ""
    try:
        if request.method == "POST":
            req = urllib.request.Request(f"http://127.0.0.1:{APP_PORT}/{path}{qs}", data=request.get_data(),
                                         headers={"Content-Type": request.content_type or "application/json",
                                                  **grok_header()})
            with urllib.request.urlopen(req, timeout=5) as r:
                return Response(r.read(), r.status, content_type=r.headers.get("Content-Type"))
        code, body, ctype = app_get(f"/{path}{qs}", timeout=5)
        return Response(body, code, content_type=ctype)
    except urllib.error.HTTPError as e:
        return Response(e.read(), e.code, content_type="application/json")
    except Exception as e:
        return say(f"Rob didn't answer ({type(e).__name__}). Try /restart.", ok=False), 502


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rob launcher (what the tunnel points at)")
    ap.add_argument("--ble", action="store_true", help="default robot = Bluetooth (default)")
    ap.add_argument("--dry", action="store_true", help="default robot = none")
    ap.add_argument("--usb", action="store_true", help="default robot = USB serial (old firmware)")
    ap.add_argument("--camera", type=int, default=None)
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--no-contacts", action="store_true")
    ap.add_argument("--no-autostart", action="store_true", help="wait for Grok's /start instead of booting now")
    ap.add_argument("--port", type=int, default=5050)
    a = ap.parse_args()
    DEFAULTS.update(robot="dry" if a.dry else "usb" if a.usb else "ble", camera=a.camera,
                    sim=a.sim, contacts=not a.no_contacts)
    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print(f"Rob launcher on :{a.port} (default robot: {DEFAULTS['robot']}). Log: {LOG}", flush=True)
    if not a.no_autostart:
        threading.Thread(target=lambda: print("[launcher]", start_app(dict(DEFAULTS))[1], flush=True),
                         daemon=True).start()
    import atexit, signal
    atexit.register(stop_app)                       # never leave the app running without the launcher
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        app.run(port=a.port, threaded=True)
    finally:
        stop_app()
