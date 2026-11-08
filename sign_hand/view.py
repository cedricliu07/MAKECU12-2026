"""The demo window: camera on the left, robot hand on the right, coaching below.
Plain grayscale, one typeface. Shapes are drawn with OpenCV, text with Pillow (real fonts)."""
import math
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from hand_cv import FINGERS, HAND_EDGES, TIP

W, H = 1600, 900
CAM_W, CAM_H = 1120, 630
BG, LINE, DIM, MID, TEXT = 16, 58, 105, 155, 236

_FONT_FILE = "/System/Library/Fonts/HelveticaNeue.ttc"
_fonts = {}


def font(size, weight="regular"):
    key = (size, weight)
    if key not in _fonts:
        idx = {"regular": 0, "bold": 1, "light": 7}[weight]
        try:
            _fonts[key] = ImageFont.truetype(_FONT_FILE, size, index=idx)
        except OSError:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


class Canvas:
    """Draw shapes on a numpy image, queue text, render text in one Pillow pass."""
    def __init__(self):
        self.img = np.full((H, W, 3), BG, np.uint8)
        self.texts = []

    def text(self, xy, s, size=20, gray=TEXT, weight="regular", anchor="la"):
        self.texts.append((xy, str(s), size, gray, weight, anchor))

    def wrap(self, x, y, s, width, size=20, gray=TEXT, weight="regular", lines=3, gap=1.3):
        f = font(size, weight)
        words, line, out = str(s).split(), "", []
        for w in words:
            t = (line + " " + w).strip()
            if f.getlength(t) <= width:
                line = t
            else:
                out.append(line); line = w
        if line:
            out.append(line)
        if len(out) > lines:
            out = out[:lines]; out[-1] = out[-1].rstrip(".,") + "…"
        for i, ln in enumerate(out):
            self.text((x, y + i * size * gap), ln, size, gray, weight)
        return y + len(out) * size * gap

    def shade(self, x0, y0, x1, y1, alpha=0.6):
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        roi = self.img[y0:int(y1), x0:int(x1)]
        roi[:] = (roi * (1 - alpha)).astype(np.uint8)

    def finish(self):
        """Blend cached text masks into the image (Pillow renders each string only once)."""
        img = self.img
        for (x, y), s, size, g, wt, anchor in self.texts:
            mask, l, t = _text_mask(s, size, wt, anchor)
            x0, y0 = int(x) + l, int(y) + t
            h, w = mask.shape
            xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
            if xa >= xb or ya >= yb:
                continue
            m = mask[ya - y0:yb - y0, xa - x0:xb - x0, None]
            roi = img[ya:yb, xa:xb]
            roi[:] = (roi * (1 - m) + g * m).astype(np.uint8)
        return img


_masks = {}


def _text_mask(s, size, weight, anchor):
    key = (s, size, weight, anchor)
    if key not in _masks:
        if len(_masks) > 3000:
            _masks.clear()
        f = font(size, weight)
        l, t, r, b = f.getbbox(s, anchor=anchor)
        im = Image.new("L", (max(1, r - l), max(1, b - t)), 0)
        ImageDraw.Draw(im).text((-l, -t), s, fill=255, font=f, anchor=anchor)
        _masks[key] = (np.asarray(im, dtype=np.float32) / 255.0, l, t)
    return _masks[key]


def draw_skeleton(frame, pts, verdict):
    """Thin white skeleton. Fingertips: filled = right, ring = needs a fix."""
    for a, b in HAND_EDGES:
        cv2.line(frame, pts[a], pts[b], (230, 230, 230), 2, cv2.LINE_AA)
    for p in pts:
        cv2.circle(frame, p, 3, (230, 230, 230), -1, cv2.LINE_AA)
    for n in FINGERS:
        p = pts[TIP[n]]
        ok = verdict is None or verdict["fingers"][n] == "ok"
        cv2.circle(frame, p, 11, (20, 20, 20), -1 if ok else 3, cv2.LINE_AA)
        cv2.circle(frame, p, 9, (245, 245, 245), -1 if ok else 2, cv2.LINE_AA)


def draw_robot_hand(img, cur, ox, oy, s=1.0, hidden=False):
    """Front view of the robot hand from the 5 curl numbers (same geometry as the real hand)."""
    g = lambda v: (v, v, v)
    if hidden:
        cv2.rectangle(img, (ox + int(70 * s), oy + int(60 * s)), (ox + int(250 * s), oy + int(320 * s)), g(LINE), 2, cv2.LINE_AA)
        return
    P = lambda x, y: (int(ox + x * s), int(oy + y * s))
    fill, edge, back = g(205), g(70), g(150)
    cv2.rectangle(img, P(104, 300), P(224, 350), fill, -1)
    cv2.rectangle(img, P(104, 300), P(224, 350), edge, 2, cv2.LINE_AA)
    pts = np.array([P(80, 210), P(96, 184), P(236, 184), P(250, 210), P(246, 300), P(224, 318), P(104, 318), P(84, 300)])
    cv2.fillPoly(img, [pts], fill, cv2.LINE_AA)
    cv2.polylines(img, [pts], True, edge, 2, cv2.LINE_AA)
    bases, widths = [100, 142, 184, 226], [31, 32, 30, 26]
    lens = [[56, 34, 26], [62, 38, 28], [58, 36, 26], [44, 28, 22]]
    for k in range(4):
        c = max(0.0, min(100.0, cur[k + 1])) / 100
        x, y, th = bases[k], 192.0, 0.0
        for j in range(3):
            th += c * math.pi / 2
            ny = y - lens[k][j] * math.cos(th)
            col = back if th > math.pi / 3 else fill
            cv2.line(img, P(x, y), P(x, ny), edge, int((widths[k] + 5) * s), cv2.LINE_AA)
            cv2.line(img, P(x, y), P(x, ny), col, int(widths[k] * s), cv2.LINE_AA)
            y = ny
    tc = max(0.0, min(100.0, cur[0])) / 100
    bx, by = 92, 288
    ang = math.radians(-128 + 98 * tc)
    ln = 96 - 24 * tc
    mid = (bx + ln * .55 * math.cos(ang), by + ln * .55 * math.sin(ang))
    tip = (bx + ln * math.cos(ang), by + ln * math.sin(ang))
    col = back if tc > .6 else fill
    for w, c in ((40, edge), (34, col)):
        cv2.line(img, P(bx, by), P(*mid), c, int(w * s), cv2.LINE_AA)
        cv2.line(img, P(*mid), P(*tip), c, int(w * s), cv2.LINE_AA)


def render(frame, st):
    """frame: BGR camera image (any size) or None. st: dict from coach.view_state()."""
    cv = Canvas()
    img = cv.img
    ses, v = st["session"], st["verdict"]
    tgt, hidden = ses["target"], not ses["show_answer"]

    # ---------------- camera
    if frame is not None:
        img[:CAM_H, :CAM_W] = cv2.resize(frame, (CAM_W, CAM_H))
    else:
        cv.text((CAM_W // 2, CAM_H // 2), st.get("camera_msg") or "No camera", 26, MID, anchor="mm")
    # target, top-left
    if tgt:
        cv.shade(24, 24, 300, 132, 0.62)
        label = {"quiz": "Which letter?", "memory": "From memory", "word": f"Spelling {ses['word']}"}.get(ses["mode"], "Target")
        big = "?" if hidden else ("ILY" if tgt == "ILY" else tgt)
        cv.text((44, 34), label.upper(), 15, MID, "bold")
        cv.text((44, 54), big, 64, TEXT, "bold")
    # hold progress / score, top-right
    if tgt and (v is not None or ses["passed"]):
        cx, cy, r = CAM_W - 78, 78, 46
        cv.shade(cx - 62, cy - 62, cx + 62, cy + 62, 0.55)
        cv2.circle(img, (cx, cy), r, (70, 70, 70), 4, cv2.LINE_AA)
        frac = 1.0 if ses["passed"] else (st["hold"] if st["hold"] > 0 else (v["score"] / 100 if v else 0))
        if frac > 0:
            cv2.ellipse(img, (cx, cy), (r, r), -90, 0, 360 * frac, (240, 240, 240), 4, cv2.LINE_AA)
        mid = "done" if ses["passed"] else ("hold" if st["hold"] > 0 else (f"{v['score']}" if v else ""))
        cv.text((cx, cy), mid, 22, TEXT, "bold", anchor="mm")
    # what it looks like
    if st["guess"] and st["hand"]:
        (l1, p1) = st["guess"][0]
        cv.shade(CAM_W - 250, CAM_H - 150, CAM_W - 24, CAM_H - 108, 0.55)
        cv.text((CAM_W - 236, CAM_H - 141), f"Looks like  {l1}  {int(p1 * 100)}%", 19, MID)
    if st["quality"]:
        cv.shade(CAM_W - 330, 148, CAM_W - 24, 186, 0.6)
        cv.text((CAM_W - 316, 157), st["quality"], 19, TEXT)
    # the one instruction, bottom of the camera
    msg = coaching_line(st)
    if msg:
        f = font(30, "bold")
        tw = min(f.getlength(msg), CAM_W - 120)
        cv.shade(CAM_W / 2 - tw / 2 - 26, CAM_H - 86, CAM_W / 2 + tw / 2 + 26, CAM_H - 28, 0.62)
        cv.text((CAM_W // 2, CAM_H - 57), msg, 30, TEXT, "bold", anchor="mm")
    if ses["flash"] or ses["celebrate"]:
        cv.shade(0, CAM_H // 2 - 80, CAM_W, CAM_H // 2 + 80, 0.55)
        cv.text((CAM_W // 2, CAM_H // 2), f"{ses['word']}  ✓" if ses["celebrate"] else "Correct", 92, 250, "bold", anchor="mm")

    # ---------------- right: the robot hand
    x0 = CAM_W + 40
    cv.text((x0, 30), "ROBOT HAND", 15, MID, "bold")
    robot_visible = st["robot_visible"]
    draw_robot_hand(img, st["robot_cur"], CAM_W + 70, 60, 1.05, hidden=not robot_visible)
    if not robot_visible:
        cv.text((CAM_W + 70 + 168, 60 + 200), "?", 90, DIM, "light", anchor="mm")
    name = "Hidden" if not robot_visible else ("?" if hidden else (st["robot_label"] or "open"))
    cv.text((x0, 440), name, 44, TEXT, "bold")
    y = 500
    if ses["how"]:
        y = cv.wrap(x0, y, ses["how"], W - x0 - 36, 20, TEXT, lines=4)
    elif ses["mode"] == "quiz" and hidden:
        y = cv.wrap(x0, y, "What letter is the robot making?", W - x0 - 36, 20, TEXT)
    elif ses["mode"] == "memory" and not robot_visible:
        y = cv.wrap(x0, y, "No help this time. Sign it from memory.", W - x0 - 36, 20, TEXT)
    if ses["tip"]:
        cv.wrap(x0, y + 8, ses["tip"], W - x0 - 36, 18, MID, lines=2)

    # ---------------- bottom-left: what Rob said, word, status
    cv2.line(img, (0, CAM_H), (W, CAM_H), (LINE,) * 3, 1)
    cv2.line(img, (CAM_W, 0), (CAM_W, H), (LINE,) * 3, 1)
    caps = ses["captions"]
    y = CAM_H + 24
    if len(caps) > 1:
        y = cv.wrap(40, y, caps[-2]["text"], CAM_W - 80, 17, DIM, lines=1)
    if caps:
        cv.text((40, y + 6), "Rob", 24, TEXT, "bold")
        y = cv.wrap(98, y + 6, caps[-1]["text"], CAM_W - 140, 24, TEXT, lines=3)
    if ses["word"]:
        bx = 40
        for i, ch in enumerate(ses["word"]):
            done = i < ses["idx"] or (i == ses["idx"] and (ses["passed"] or ses["celebrate"]))
            box = (bx, H - 128, bx + 46, H - 76)
            if done:
                cv2.rectangle(img, box[:2], box[2:], (225, 225, 225), -1, cv2.LINE_AA)
            cv2.rectangle(img, box[:2], box[2:], (235, 235, 235) if i == ses["idx"] else (LINE,) * 3,
                          2, cv2.LINE_AA)
            cv.text((bx + 23, H - 102), ch, 26, BG if done else (TEXT if i == ses["idx"] else DIM), "bold", anchor="mm")
            bx += 54
    status = "   ·   ".join(s for s in [
        {"free": "Free", "teach": "Learning", "word": "Word practice", "quiz": "Quiz", "memory": "From memory"}.get(ses["mode"], ses["mode"]),
        st["robot_link"], st["camera_status"], st["grok_status"]] if s)
    cv.text((40, H - 50), status, 16, MID)
    cv.text((40, H - 26), "Keys:  letter = teach   3 next   4 quiz   5 from memory   6 practice word   7 free   "
                           "0 open   1 / 2 calibrate open / fist   esc quit", 14, DIM)

    # ---------------- bottom-right: fingers vs target + progress
    cv.text((x0, CAM_H + 22), "YOUR FINGERS", 15, MID, "bold")
    ts, lc = st["target_shape"], st["learner"]
    show_zone = ts is not None and not hidden and robot_visible
    tx0, tx1 = x0 + 74, W - 96
    for i, n in enumerate(FINGERS):
        yy = CAM_H + 56 + i * 27
        cv.text((x0, yy - 9), n.capitalize(), 16, MID)
        cv2.rectangle(img, (tx0, yy - 6), (tx1, yy + 6), (40, 40, 40), -1, cv2.LINE_AA)
        if show_zone:
            lo, hi = max(0, ts[i] - st["tol"][i]), min(100, ts[i] + st["tol"][i])
            cv2.rectangle(img, (int(tx0 + (tx1 - tx0) * lo / 100), yy - 6),
                          (int(tx0 + (tx1 - tx0) * hi / 100), yy + 6), (82, 82, 82), -1)
        if lc is not None:
            xe = int(tx0 + (tx1 - tx0) * max(2, lc[i]) / 100)
            cv2.rectangle(img, (tx0, yy - 3), (xe, yy + 3), (235, 235, 235), -1)
            cv2.line(img, (xe, yy - 10), (xe, yy + 10), (245, 245, 245), 2)
            if v is not None and not hidden:
                cv.text((tx1 + 14, yy - 9), {"ok": "ok", "bend": "bend", "straighten": "open"}[v["fingers"][n]],
                        15, TEXT if v["fingers"][n] != "ok" else MID)
    # progress through the lesson letters
    cv.text((x0, H - 82), f"PASSED  {len(ses['mastered'])}/{len(ses['curriculum'])}     STREAK  {ses['streak']}",
            15, MID, "bold")
    px = x0
    for L in ses["curriculum"]:
        box = (px, H - 58, px + 26, H - 30)
        done = L in ses["mastered"]
        if done:
            cv2.rectangle(img, box[:2], box[2:], (220, 220, 220), -1)
        cv2.rectangle(img, box[:2], box[2:], (235, 235, 235) if (L == tgt and not hidden) else (LINE,) * 3, 1)
        cv.text((px + 13, H - 44), L, 15, BG if done else MID, "bold", anchor="mm")
        px += 32
    return cv.finish()


def coaching_line(st):
    ses, v = st["session"], st["verdict"]
    tgt, hidden = ses["target"], not ses["show_answer"]
    if not st["hand"]:
        return "Show your hand to the camera" if tgt or ses["mode"] == "free" else ""
    if ses["mode"] == "free" or not tgt:
        return ""
    if ses["passed"]:
        if ses["mode"] == "word":
            return f"Next: {ses['word'][ses['idx'] + 1]}" if ses["idx"] < len(ses["word"]) - 1 else f"You spelled {ses['word']}"
        return "Correct. Say “next” for a new letter."
    if v is None:
        return ""
    if hidden and ses["mode"] == "quiz":
        return "What letter is the robot making?"
    return v["fix"]
