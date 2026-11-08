# Rob: a robot hand that teaches ASL fingerspelling

Talk to Rob through Grok Bot. Say "teach me D" and the robot hand forms D while Rob
explains it in plain words. The laptop camera watches your hand, and the window shows
**Correct** with a chime the moment you get it right.

```
You (voice) → Grok Bot → cloudflared tunnel → coach.py (laptop :5050) ─┬→ Bluetooth → ESP32 (test_bt) → 5 servos
                                                                        ├→ camera + MediaPipe → judges your hand
                                                                        └→ window: camera + robot hand + coaching
```

## Architecture

```
Grok (HTTPS) → cloudflared → rob.py :5050
                               │  /start /stop /restart /status /logs /help
                               │  other paths forwarded (boot app if needed)
                               ▼
                         coach.py :5051
                               │
               ┌───────────────┼────────────────┐
               ▼               ▼                ▼
         ble_out.py      hand_cv.py         view.py
         (Bluetooth)     (judge / see)      (demo window)
               │               ▲
               ▼               │
         ESP32 hand      lessons.Session
                         (teach / quiz / word / memory)
```

| File | What it does |
|---|---|
| `rob.py` | Launcher on :5050 (what the tunnel points at). Grok uses it to boot / stop / restart the app and check its health; it forwards everything else to the app and boots it on demand. Fixed command menu only. |
| `coach.py` | The Rob app: robot + camera window + teaching API (port 5051 when run by the launcher). |
| `hand_cv.py` | Measures a hand from MediaPipe 3D landmarks, judges a letter, recognizes letters. |
| `lessons.py` | Teaching content, modes (learn / word / quiz / memory / free), progress. |
| `ble_out.py` | Bluetooth output to Cedric's `test_bt` firmware. |
| `view.py` | The demo window: camera, robot hand, finger bars, what Rob said, progress. |
| `GROK_PROMPT.txt` | Prompt for Grok (`start.sh` fills in the tunnel URL and copies it). |

## Run
```sh
python3 -m pip install -r sign_hand/requirements.txt
bash sign_hand/start.sh --ble          # tunnel + coach, robot over Bluetooth
bash sign_hand/start.sh --dry          # no robot
python3 sign_hand/coach.py --dry --sim # no camera: a fake learner copies the robot (test / backup)
```
Then paste the prompt (already on the clipboard) into a **new** Grok chat, send, and go live voice.
Other flags: `--camera N` (default = the Mac's built-in camera, never the iPhone) ·
`--no-contacts` (judge finger curls only) · `--no-chime`.

## Tests
Offline suite (no camera, Bluetooth, or network):
```sh
cd sign_hand && python3 -m pytest -q
```
Covers `hand_cv` (features / judge / recognize / calibration), `lessons` Session flows,
`ble_out` angle mapping + stagger, coach HTTP routes via Flask's `test_client`, and
`rob.py` helpers (`/help`, `opts_from_query`, `log_tail`).

## Grok runs everything
`start.sh` starts the tunnel and the launcher. From then on, Grok can drive the whole thing:
| Say | Route | What happens |
|---|---|---|
| "start Rob" | `/start` (`?robot=ble\|dry`, `&sim=1`) | Opens the camera window, connects the robot |
| "close Rob" | `/stop` | Closes it |
| "it's stuck" | `/restart` (`?robot=dry` = without the robot) | Restarts it |
| "is it working?" | `/status` | Robot connected? Camera on? Hand in view? Plus the last problem |
| "what went wrong?" | `/logs` | The last log lines |
| (unsure) | `/help` | The full command menu as JSON |

Any teaching command (`/teach/D` …) boots the app first if it isn't running. If you press Esc,
the window closes, and the next command from Grok reopens it.

## How the camera judges a sign
Robot and learner share one description: 5 numbers, how curled each finger is
(0 = straight, 100 = curled; thumb, index, middle, ring, pinky).
- Measured from MediaPipe **3D world landmarks**, so moving or turning the hand a little doesn't change it.
- The thumb uses its reach across the palm (thumb tip → pinky knuckle), which separates thumb-out (L, Y) from thumb-across (B, W).
- Contact checks separate look-alikes: O / F (thumb touches index), D (thumb touches middle), C (gap), U (fingers together), W (spread).
- The sign must be **held 0.6 s** to count, which stops flicker false-positives. Then: chime, Correct!, progress.
- A recognizer compares the hand with every letter, so Rob can say "that looks more like C" or answer "what am I signing?".
- Calibration (optional, improves accuracy): open hand → key `1`, fist → key `2`.

## Modes (voice via Grok, or keys in the window)
| Say | Route | What happens |
|---|---|---|
| "teach me D" | `/teach/D` | Robot holds D, Rob explains, the camera checks you |
| "next" | `/next` | Next letter in the lesson path L Y B I A W U D F O C E X |
| "check me" | `/check` | Camera verdict + the one fix to make |
| "what am I signing?" | `/see` | Recognizes your hand |
| "help" | `/hint` | Live fix + common mistake + memory tip |
| "let's practice FOOD" | `/practice/FOOD` | Letter by letter; advances by itself when you get each one |
| "spell FOOD" | `/spell/FOOD` | Robot spells it |
| "quiz me" → "is it L?" | `/quiz` → `/guess/L` | Robot signs a hidden letter, you guess |
| "test me" | `/memory` | Sign from memory, robot hidden until you pass |
| "how am I doing?" | `/progress` | Letters passed, best streak |

Every route answers in ~1–4 ms with `{"say": "..."}`, a sentence Grok can speak as-is.
Letters the robot can't form (G H J K M N P Q R S T V Z) are explained in words.
Window keys: letter = teach (in a quiz: guess) · `3` next · `4` quiz · `5` from memory ·
`6` practice a random word · `7` free · `0` open · `1`/`2` calibrate open hand / fist · `esc` quit.

## Hardware
| Finger | Thumb | Index | Middle | Ring | Pinky |
|---|---|---|---|---|---|
| GPIO | 18 | 19 | 21 | 22 | 23 |

Servos are powered from the 5 V supply through the power distribution node, never from
the ESP32. Tie the supply GND to the ESP32 GND.

**Bluetooth (`--ble`)**: flash `test_bt` (top-level README). coach.py finds
`ESP32-Servo-Controller` (by name or service UUID), streams eased `A,a0..a4` angles about
25 times a second (only when they change), and reconnects by itself. Only one Bluetooth
client at a time: close `ble_servo.py` / `pattern.py` first. macOS asks once to allow
Bluetooth for Terminal.

**Calibrate the servos** before attaching the tendons: `curl localhost:5050/raw/90,90,90,90,90`
(thumb..pinky) sets angles directly. Defaults follow `test_bt`: 180 = straight, 0 = curled
(the firmware reverses ring + pinky itself). Find each finger's straight and curled angle, put them
in `OPEN_DEG` / `CLOSED_DEG` in `ble_out.py`, then `curl localhost:5050/raw/off`.

Legacy: `firmware/sign_hand/sign_hand.ino` + USB serial (`coach.py` without `--ble`/`--dry`),
and `bridge.py` (robot only). Old routes (`POST /sign`, `/check?letter=`, `/status`) still work.
