#!/usr/bin/env python3
"""
"Rob" sign-language coach: ONE program on the laptop that does everything.

  Grok Bot (live voice) --HTTPS--> cloudflared tunnel --> this server (:5050)
     -> moves the robot hand (Bluetooth / USB / dry) + the on-screen twin
     -> watches the learner with the camera and judges the sign
     -> returns ONE short sentence ("say") for Grok to speak

  Demo window: camera + robot hand + coaching (view.py). Keys work without Grok.

Files: hand_cv.py (measuring + judging hands) · lessons.py (content, modes, progress)
       ble_out.py (Bluetooth to Cedric's test_bt firmware) · view.py (the window)

Run:  bash sign_hand/start.sh --ble        (tunnel + this, robot over Bluetooth)
      python3 sign_hand/coach.py --dry     (no robot)    · --sim  (no camera: fake learner, for testing)
"""
import argparse, glob, os, re, subprocess, sys, threading, time, urllib.request

import cv2
import numpy as np
from flask import Flask, request

import hand_cv as hc
from hand_cv import ALLOWED, FINGERS, SHAPES
import lessons
from lessons import CONTENT, WORDS, WORDS_ONLY, Session
import view

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "hand_landmarker.task")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")

ser = None
DRY = False
CHIME = True
BLE = None          # ble_out.BleOut when run with --ble


# ================================================================ robot (+ on-screen twin)
def find_port(explicit):
    if explicit:
        return explicit
    for pat in ("/dev/cu.usbserial*", "/dev/cu.SLAB_USBtoUART*", "/dev/cu.wchusbserial*", "/dev/cu.usbmodem*"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


class DigitalHand:
    """Plays the same commands the ESP32 gets. BLE output follows target_now() too."""
    HOLD, MOVE = 1.2, 0.3

    def __init__(self):
        self.cur = [0.0] * 5
        self.seq, self.t_start, self.label = [], 0.0, ""

    def command(self, line):
        if line.startswith("SHOW "):
            c = line[5:].strip()
            self.seq = [(c, SHAPES[c], None)] if c in SHAPES else []
        elif line in ("ILYHOLD", "ILY"):
            self.seq = [("I love you", SHAPES["ILY"], None if line == "ILYHOLD" else 2 * self.HOLD)]
        elif line.startswith("SPELL "):
            self.seq = [(c, SHAPES[c], self.HOLD) for c in line[6:].strip() if c in SHAPES]
        elif line == "OPEN":
            self.seq = []
        self.t_start = time.time()

    def target_now(self):
        t = time.time() - self.t_start
        for name, shape, dur in self.seq:
            if dur is None or t < dur + self.MOVE:
                return name, shape
            t -= dur + self.MOVE
        return "", [0] * 5

    def run(self):                                   # 60 Hz easing thread
        while True:
            self.label, tgt = self.target_now()
            for i in range(5):
                self.cur[i] += (tgt[i] - self.cur[i]) * 0.15
            time.sleep(1 / 60)


ROBO = DigitalHand()


def send(line):
    print(f"--> robot: {line}", flush=True)
    ROBO.command(line)
    if BLE is not None:
        BLE.clear_raw()
    if not DRY and ser is not None:
        ser.write((line + "\n").encode()); ser.flush()


SES = Session(send)


def robot_link():
    if BLE is not None:
        return {"kind": "bluetooth", "ok": BLE.connected, "text": "Bluetooth " + ("connected" if BLE.connected else "searching…")}
    if DRY:
        return {"kind": "dry", "ok": True, "text": "Robot: dry run"}
    return {"kind": "usb", "ok": ser is not None, "text": f"USB {ser.port}" if ser else "USB not connected"}


# ================================================================ live vision state
class Live:
    def __init__(self):
        self.lock = threading.Lock()
        self.camera_on = True
        self.camera_ok = False
        self.hand_seen_at = 0.0
        self.feat = None
        self.curls = None
        self.verdict = None
        self.ranked = []
        self.hold = 0.0
        self.hold_start = None
        self.quality = ""
        self.fps = 0.0
        self.grok_at, self.grok_path = 0.0, ""
        self.grok_log = []

LIVE = Live()
CAL = hc.Calibration()


def hand_visible(window=1.0):
    return time.time() - LIVE.hand_seen_at < window


def check(letter):
    """INSTANT verdict from what the camera already sees (never waits)."""
    L = norm_letter(letter) or (SES.target or "")
    if L not in SHAPES:
        return {"ok": False, "match": False, "hand_visible": hand_visible(),
                "say": "Ask me to teach a letter first, then I can check it."}
    with LIVE.lock:
        curls, feat, ranked = LIVE.curls, LIVE.feat, list(LIVE.ranked)
    recent_pass = any(e.get("pass") == L and time.time() - e["t"] < 4 for e in list(SES.events))
    if curls is None or not hand_visible(4):
        return {"ok": True, "match": recent_pass, "hand_visible": False,
                "say": "Perfect, you had it!" if recent_pass else
                "I can't see your hand. Hold it up to the camera, palm facing it."}
    v = hc.judge(L, curls, feat)
    if v["match"] or recent_pass:
        return {"ok": True, "match": True, "hand_visible": True, "score": max(v["score"], 90),
                "say": f"Perfect, that's {'I love you' if L == 'ILY' else L}!"}
    say = v["fix"]
    if ranked and ranked[0][0] != L and ranked[0][1] > 0.45:
        say = f"That looks more like {ranked[0][0]}. {say}"
    return {"ok": True, "match": False, "hand_visible": True, "score": v["score"], "say": say}


def see():
    with LIVE.lock:
        ranked = list(LIVE.ranked)
    if not hand_visible(1.5) or not ranked:
        return "I can't see your hand right now."
    (L1, p1), (L2, _) = ranked[0], ranked[1]
    name = "I love you" if L1 == "ILY" else L1
    if p1 > 0.5:
        return f"That looks like {name}."
    return f"Hmm, somewhere between {L1} and {L2}."


def norm_letter(x):
    t = re.sub(r"[^A-Z]", "", str(x or "").upper())
    if t in ("ILY", "ILOVEYOU", "LOVEYOU"):
        return "ILY"
    return t[:1]


# ================================================================ web API
app = Flask(__name__)

@app.before_request
def note_grok():
    if "Cf-Ray" in request.headers or "Cf-Connecting-Ip" in request.headers:   # came through the tunnel
        LIVE.grok_at, LIVE.grok_path = time.time(), request.path
        LIVE.grok_log = (LIVE.grok_log + [{"t": time.time(), "path": request.path}])[-6:]
        print(f"[grok] {request.path}", flush=True)

def reply(say, **kw):
    return {"ok": kw.pop("ok", True), "say": say, **kw}

# ---- local actions (keyboard): same as Grok's, so the demo works without voice
def do_action(action, arg=""):
    a = arg.upper()
    if action == "teach":      return SES.teach(norm_letter(a))
    if action == "word":       return SES.word_practice(a)
    if action == "quiz":       return SES.quiz()
    if action == "guess":      return SES.guess(norm_letter(a))
    if action == "memory":     return SES.memory(norm_letter(a) or None)
    if action == "free":       return SES.free()
    if action == "next":       return SES.next_letter()
    if action == "calibrate":
        with LIVE.lock:
            f = LIVE.feat
        if f is None or not hand_visible(0.5):
            return SES.say("Show your hand first.")
        CAL.capture(f, "open" if a == "OPEN" else "fist")
        return SES.say(f"Calibrated your {'open hand' if a == 'OPEN' else 'fist'}.")
    if action == "open":
        return SES.free()
    return ""


def view_state():
    with LIVE.lock:
        v, ranked, curls = LIVE.verdict, LIVE.ranked[:3], LIVE.curls
        hold, quality, fps = LIVE.hold, LIVE.quality, LIVE.fps
    s = SES.snapshot()
    hand = hand_visible(0.6)
    ga = time.time() - LIVE.grok_at if LIVE.grok_at else None
    return {
        "session": s, "verdict": v if hand else None, "hold": hold, "hand": hand,
        "guess": ranked if hand else [], "learner": curls if hand else None,
        "quality": quality if hand else "", "target_shape": SHAPES.get(s["target"]), "tol": hc.TOL,
        "robot_cur": list(ROBO.cur), "robot_label": ROBO.label,
        "robot_visible": s["mode"] != "memory" or s["passed"],
        "robot_link": robot_link()["text"],
        "camera_status": (f"Camera {fps:.0f} fps" if LIVE.camera_ok else "No camera"),
        "grok_status": "Grok: waiting" if ga is None else ("Grok: now" if ga < 2 else f"Grok: {ga:.0f} s ago"),
    }


# ---- Grok: one short GET each, the reply's "say" is what Rob speaks
@app.get("/teach/<letter>")
def g_teach(letter):
    L = norm_letter(letter)
    return reply(SES.teach(L), ok=L in CONTENT, showing=L if L in CONTENT else "")

@app.get("/next")
def g_next():
    return reply(SES.next_letter(), showing=SES.target)

@app.get("/check")
@app.get("/check/<letter>")
def g_check(letter=""):
    r = check(letter or request.args.get("letter", ""))
    SES.say(r["say"])
    return r

@app.get("/see")
def g_see():
    return reply(SES.say(see()))

@app.get("/hint")
def g_hint():
    live = check("")["say"] if SES.target in SHAPES and hand_visible(1) else None
    if live and live.startswith("Perfect"):
        live = None
    return reply(SES.hint(live))

@app.get("/spell/<word>")
def g_spell(word):
    letters = "".join(ch for ch in word.upper() if ch in ALLOWED)
    if not letters:
        return reply(SES.say("The robot can't form any of those letters."), ok=False)
    send(f"SPELL {letters}")
    skipped = sorted(set(ch for ch in word.upper() if ch.isalpha() and ch not in ALLOWED))
    note = f" The robot skips {', '.join(skipped)}." if skipped else ""
    return reply(SES.say("Watch: " + ", ".join(letters) + "." + note), signed=letters)

@app.get("/practice")
@app.get("/practice/<word>")
def g_practice(word=""):
    return reply(SES.word_practice(word))

@app.get("/quiz")
def g_quiz():
    return reply(SES.quiz())

@app.get("/guess/<letter>")
def g_guess(letter):
    return reply(SES.guess(norm_letter(letter)))

@app.get("/memory")
@app.get("/memory/<letter>")
def g_memory(letter=""):
    return reply(SES.memory(norm_letter(letter) or None))

@app.get("/free")
def g_free():
    return reply(SES.free())

@app.get("/progress")
def g_progress():
    return reply(SES.progress())

@app.get("/explain/<letter>")
def g_explain(letter):
    L = norm_letter(letter)
    text = CONTENT[L][0] if L in CONTENT else WORDS_ONLY.get(L, "Which letter?")
    return reply(SES.say(text))

@app.get("/ily")
def g_ily():
    return reply(SES.teach("ILY"), showing="ILY")

@app.get("/open")
@app.post("/open")
def g_open():
    SES.free()
    return reply("Okay.")

@app.get("/show/<letter>")
def g_show(letter):
    L = norm_letter(letter)
    if L in CONTENT:
        SES._set_target(L, "teach")
    return {"ok": L in CONTENT, "showing": L}

# ---- older routes (kept so old prompts still work)
@app.get("/status")
def status():
    return {"ok": True, "robot": robot_link()["text"], "camera_on": LIVE.camera_on,
            "target": SES.target, "hand_visible": hand_visible(0.5),
            "robot_letters": "".join(sorted(ALLOWED)) + " + ILY"}

@app.post("/sign")
def sign():
    d = request.get_json(silent=True)
    if d is None:
        d = {"text": request.get_data(as_text=True)}
    if isinstance(d, dict) and d.get("letter"):
        L = norm_letter(d["letter"])
        return reply(SES.teach(L), ok=L in CONTENT, showing=L)
    t = ""
    if isinstance(d, dict):
        for k in ("word", "sign", "text", "letters", "spell", "message"):
            if d.get(k):
                t = "".join(d[k]) if isinstance(d[k], list) else str(d[k]); break
    else:
        t = str(d)
    if re.sub(r"[^A-Z]", "", t.upper()) in ("ILOVEYOU", "ILY", "LOVEYOU"):
        return g_ily()
    if len(re.sub(r"[^A-Z]", "", t.upper())) == 1:
        return g_teach(t)
    return g_spell(t)

@app.get("/camera/<onoff>")
@app.post("/camera/<onoff>")
def camera_onoff(onoff):
    LIVE.camera_on = onoff in ("start", "on")
    return {"ok": True, "camera_on": LIVE.camera_on}

@app.post("/calibrate/<which>")
def calibrate_legacy(which):
    return reply(do_action("calibrate", which))

@app.get("/raw/<path:vals>")
def raw(vals):
    """Calibration: /raw/90,90,90,90,90 sets servo angles directly (BLE mode). /raw/off ends it."""
    if BLE is None:
        return {"ok": False, "say": "Raw angles need --ble."}
    if vals == "off":
        BLE.clear_raw(); return {"ok": True, "raw": None}
    try:
        a = [int(v) for v in vals.split(",")]; assert len(a) == 5
    except Exception:
        return {"ok": False, "say": "Use /raw/a0,a1,a2,a3,a4 (thumb..pinky, 0-180)."}
    BLE.set_raw(a)
    return {"ok": True, "raw": BLE.raw}


# ================================================================ camera loop (main thread)
def pick_camera(explicit):
    """Default to the Mac's built-in camera, never the iPhone (Continuity Camera)."""
    if explicit is not None:
        return explicit
    try:
        import AVFoundation as AV
        devs = list(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeVideo)) + \
               list(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeMuxed))
    except Exception:
        print("(camera auto-pick unavailable: pip3 install pyobjc-framework-AVFoundation) using 0")
        return 0
    names = [f"{i}={d.localizedName()}" for i, d in enumerate(devs)]
    pick = next((i for i, d in enumerate(devs) if "builtin" in str(d.deviceType()).lower()), None)
    if pick is None:
        phone = lambda d: any(k in f"{d.deviceType()} {d.localizedName()} {d.modelID()}".lower()
                              for k in ("continuity", "iphone", "ipad"))
        pick = next((i for i, d in enumerate(devs) if not phone(d)), 0)
    print(f"Cameras: {', '.join(names) or 'none'}  -> using {pick}", flush=True)
    return pick


def chime():
    if CHIME:
        subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def process(curls, feat, now):
    """Shared by real camera + --sim: smoothing, judging, hold-to-pass."""
    with LIVE.lock:
        if LIVE.curls is None or now - LIVE.hand_seen_at > 0.5:
            LIVE.curls = list(curls)
        else:                                       # light smoothing: steady but responsive
            LIVE.curls = [0.55 * c + 0.45 * p for c, p in zip(curls, LIVE.curls)]
        LIVE.feat, LIVE.hand_seen_at = feat, now
        sm = list(LIVE.curls)
    L = SES.target
    v = hc.judge(L, sm, feat) if L in SHAPES else None
    ranked, _ = hc.recognize(sm, feat)
    with LIVE.lock:
        LIVE.verdict, LIVE.ranked = v, ranked
        if v and v["match"]:
            LIVE.hold_start = LIVE.hold_start or now
            LIVE.hold = min(1.0, (now - LIVE.hold_start) / lessons.HOLD_TO_PASS)
        else:
            LIVE.hold_start, LIVE.hold = None, 0.0
        passed = LIVE.hold >= 1.0
    if passed and SES.on_pass(L, now):
        chime()
        print(f"[pass] {L}", flush=True)
    return v


WIN = "Rob - ASL coach"
KEYS = {ord("3"): ("next", ""), ord("4"): ("quiz", ""), ord("5"): ("memory", ""),
        ord("7"): ("free", ""), ord("0"): ("open", ""), ord("1"): ("calibrate", "open"),
        ord("2"): ("calibrate", "fist")}


def show(frame):
    """Draw the window and handle keys. Returns False to quit."""
    cv2.imshow(WIN, view.render(frame, view_state()))
    k = cv2.waitKey(1) & 0xFF
    if k == 27:                                     # esc
        return False
    if k in KEYS:
        do_action(*KEYS[k])
    elif k == ord("6"):
        import random
        do_action("word", random.choice(WORDS))
    elif k != 255 and chr(k).isalpha():
        L = chr(k).upper()
        st = SES.snapshot()
        do_action("guess" if st["mode"] == "quiz" and not st["show_answer"] else "teach", L)
    return True


def open_window():
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, 1440, 810)


def sim_loop():
    """--sim: no camera. A fake learner copies the robot after ~1.5 s (tests everything else)."""
    print("SIM mode: fake learner, no camera", flush=True)
    LIVE.camera_ok = True
    rng = np.random.default_rng(0)
    open_window()
    while True:
        now = time.time()
        L = SES.target
        if L in SHAPES and now - SES.target_since > 1.5:
            curls = [c + rng.normal(0, 6) for c in SHAPES[L]]
            feat = {"bends": {}, "reach": 0.8, "spread": 1.0 if L == "U" else 2.0,
                    "touch_i": 0.2 if L in ("O", "F") else 0.6, "touch_m": 0.2 if L == "D" else 0.6}
            process(curls, feat, now)
        elif L in SHAPES:
            process([50 + rng.normal(0, 10) for _ in range(5)], {"bends": {}, "reach": 0.8, "spread": 1.5,
                    "touch_i": 0.5, "touch_m": 0.5}, now)
        SES.tick(now)
        frame = np.full((540, 960, 3), 34, np.uint8)
        cv2.putText(frame, "simulated learner (no camera)", (300, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (120, 120, 120), 2, cv2.LINE_AA)
        if not show(frame):
            break
        time.sleep(1 / 40)


def camera_loop(cam_index):
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    if not os.path.exists(MODEL):
        print("Downloading hand model (~8 MB)...", flush=True)
        urllib.request.urlretrieve(MODEL_URL, MODEL)
    landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL),
        running_mode=vision.RunningMode.VIDEO, num_hands=1,
        min_hand_detection_confidence=0.5, min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5))
    open_window()
    print("Opening camera...", flush=True)
    cam_index = pick_camera(cam_index)
    cap = cv2.VideoCapture(cam_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
    for _ in range(40):
        if cap.read()[0]:
            break
        time.sleep(0.05)
    LIVE.camera_ok = cap.isOpened() and cap.read()[0]
    print("Camera ready." if LIVE.camera_ok else
          f"!! Camera {cam_index} gave no picture. Try --camera 1.", flush=True)
    t0, ts, fps_t, n = time.time(), 0, time.time(), 0
    while True:
        now = time.time()
        SES.tick(now)
        ok, frame = cap.read()
        if not ok:
            if not show(None):
                break
            time.sleep(0.05)
            continue
        frame = cv2.flip(frame, 1)                   # mirror view
        h, w = frame.shape[:2]
        if LIVE.camera_on:
            ts = max(ts + 1, int((now - t0) * 1000))
            res = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB,
                         data=cv2.cvtColor(cv2.resize(frame, (640, 360)), cv2.COLOR_BGR2RGB)), ts)   # smaller = faster
            if res.hand_landmarks:
                lm = res.hand_landmarks[0]
                pts = [(int(p.x * w), int(p.y * h)) for p in lm]
                feat = hc.features([[p.x, p.y, p.z] for p in res.hand_world_landmarks[0]])
                v = process(CAL.curls(feat), feat, now)
                size = np.hypot(pts[0][0] - pts[9][0], pts[0][1] - pts[9][1])
                out = any(p.x < 0.02 or p.x > 0.98 or p.y < 0.02 or p.y > 0.98 for p in lm)
                LIVE.quality = ("Move your hand closer" if size < 0.11 * h else
                                "Keep your whole hand in view" if out else "")
                view.draw_skeleton(frame, pts, v)
            else:
                LIVE.quality = ""
                with LIVE.lock:
                    LIVE.hold_start, LIVE.hold = None, 0.0
        n += 1
        if now - fps_t > 1:
            LIVE.fps, n, fps_t = n / (now - fps_t), 0, now
        if not show(frame):
            break
    cap.release()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=None, help="camera number; default = the Mac's built-in camera")
    ap.add_argument("--port", default=None, help="USB serial port (old firmware)")
    ap.add_argument("--dry", action="store_true", help="no robot")
    ap.add_argument("--ble", action="store_true", help="robot over Bluetooth (Cedric's test_bt firmware)")
    ap.add_argument("--sim", action="store_true", help="no camera: fake learner copies the robot")
    ap.add_argument("--no-contacts", action="store_true", help="judge finger curls only (if O/C/U/W checks misfire)")
    ap.add_argument("--http-port", type=int, default=5050)
    ap.add_argument("--no-chime", action="store_true")
    a = ap.parse_args()
    DRY, CHIME = a.dry, not a.no_chime
    hc.USE_CONTACTS = not a.no_contacts
    threading.Thread(target=ROBO.run, daemon=True).start()
    if a.ble:
        import ble_out
        BLE = ble_out.BleOut(ROBO); BLE.start()
        print("BLUETOOTH mode: driving ESP32-Servo-Controller (test_bt firmware)")
    elif not DRY:
        port = find_port(a.port)
        if not port:
            print("!! No robot found. Use --ble (Bluetooth), plug in USB, or run with --dry.")
            sys.exit(1)
        import serial
        ser = serial.Serial(port, 115200, timeout=1); time.sleep(2)
        print(f"Connected to ESP32 on {port}")
    else:
        print("DRY RUN: robot commands are only printed")
    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)      # keep the terminal readable
    threading.Thread(target=lambda: app.run(port=a.http_port, threaded=True), daemon=True).start()
    try:
        sim_loop() if a.sim else camera_loop(a.camera)
    except KeyboardInterrupt:
        pass
