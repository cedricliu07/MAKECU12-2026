"""Teaching content + the learning session (modes, progress, captions) for the Rob coach."""
from __future__ import annotations

import random
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from hand_cv import ALLOWED, SHAPES

# how = what to do (spoken), tip = memory hook, mistake = the classic error.
CONTENT = {
    "A": ("Make a fist, with your thumb resting straight up along the side of your index finger.",
          "Think of a rock with the thumb on its side.", "Don't tuck the thumb inside, that's an S."),
    "B": ("Hold four fingers straight up and together, and fold your thumb across your palm.",
          "Like a flat stop sign.", "Keep the thumb folded in, not sticking out."),
    "C": ("Curve your fingers and thumb into a C, like you're holding a cup.",
          "Your hand draws the letter C.", "Leave a gap; if the tips touch, it's an O."),
    "D": ("Point your index finger straight up, and touch your thumb to your other curled fingertips.",
          "The finger and the circle make a lowercase d.", "Keep that index finger straight."),
    "E": ("Bend all four fingertips down to rest on your thumb, tucked across your palm.",
          "Like a claw hiding the thumb.", "It's not a full fist; the fingertips sit on the thumb."),
    "F": ("Touch your index fingertip to your thumb, and keep the other three fingers up.",
          "It looks like an OK sign.", "The other three fingers stay straight and apart."),
    "I": ("Make a fist and raise only your pinky straight up.",
          "The pinky is a tiny letter I.", "Keep the thumb across your fingers."),
    "L": ("Stretch your thumb out and your index finger up, like an L, and curl the rest.",
          "Thumb and index draw an L.", "Keep the other three fingers curled."),
    "O": ("Curve all your fingers to meet your thumb, making a round O.",
          "Like looking through a telescope.", "The tips must touch; a gap makes it a C."),
    "U": ("Hold your index and middle fingers straight up and together; your thumb holds the other two down.",
          "Two fingers glued together, like a U.", "Keep them touching; apart is a V."),
    "W": ("Raise your index, middle and ring fingers spread apart; your thumb holds the pinky down.",
          "Three fingers are the three points of a W.", "Spread them, and keep the pinky down."),
    "X": ("Make a fist, then raise your index finger and bend it into a hook.",
          "A hook, like a pirate's finger.", "Bend it; a straight index is closer to D."),
    "Y": ("Stretch out your thumb and pinky, and curl the three middle fingers.",
          "The hang-loose shaka.", "Keep the middle three curled tight."),
    "ILY": ("Thumb, index and pinky out; middle and ring fingers down.",
            "It's I, L and Y in one hand.", "Keep the middle and ring fingers down."),
}
# Letters the robot can't form: explained in words only.
WORDS_ONLY = {
    "G": "Point your index finger sideways with your thumb parallel above it.",
    "H": "Point your index and middle fingers sideways, together.",
    "J": "Make an I, then draw a J in the air with your pinky.",
    "K": "Index up, middle finger angled forward, thumb touching between them.",
    "M": "Fold your thumb under your index, middle and ring fingers.",
    "N": "Fold your thumb under your index and middle fingers.",
    "P": "Make a K, then point it down.",
    "Q": "Make a G, then point it down.",
    "R": "Cross your middle finger over your index finger.",
    "S": "Make a fist with your thumb across the front of your fingers.",
    "T": "Make a fist with your thumb tucked between your index and middle fingers.",
    "V": "Index and middle fingers up and spread, like a peace sign.",
    "Z": "Draw a Z in the air with your index finger.",
}
CURRICULUM = ["L", "Y", "B", "I", "A", "W", "U", "D", "F", "O", "C", "E", "X"]
WORDS = ["FOOD", "COOL", "LIFE", "FACE", "CODE", "IDEA", "FLY", "COW", "BLUE", "YELLOW",
         "WOLF", "CLOUD", "BABY", "FIELD", "LOYAL"]

HOLD_TO_PASS = 0.6     # seconds the right shape must be held to count
ADVANCE_DELAY = 1.0    # pause on "Correct!" before the next letter of a word


class Session:
    """Learning state shared by the Grok API, the camera loop and the window."""
    def __init__(self, robot_cmd: Callable[[str], Any]) -> None:
        self.robot_cmd = robot_cmd            # function(line) -> moves robot + twin
        self.lock = threading.RLock()
        self.mode = "free"                    # free | teach | word | quiz | memory
        self.target: str | None = None
        self.show_answer = True               # window shows target letter + robot
        self.word, self.idx = "", 0
        self.quiz_answer: str | None = None
        self.instance = 0                     # bumps on every new target (so each pass counts once)
        self.passed_instance = -1
        self.target_since = 0.0
        self.stats: dict[str, dict[str, Any]] = {L: {"tries": 0, "passed": 0, "best": None} for L in SHAPES}
        self.streak = self.best_streak = self.total = 0
        self.captions: deque[dict[str, Any]] = deque(maxlen=6)
        self.flash_until = 0.0
        self.celebrate_until = 0.0
        self.pending_advance: float | None = None
        self.events: deque[dict[str, Any]] = deque(maxlen=20)

    # ---------------------------------------------------------- helpers
    def say(self, text: str, who: str = "rob") -> str:
        """Append a caption and return the same sentence for Grok to speak."""
        with self.lock:
            self.captions.append({"who": who, "text": text, "t": time.time()})
        return text

    def _set_target(self, L: str, mode: str, show_robot: bool = True, show_answer: bool = True) -> None:
        with self.lock:
            self.mode, self.target, self.show_answer = mode, L, show_answer
            if mode != "word":
                self.word, self.idx = "", 0
            self.instance += 1
            self.target_since = time.time()
            if L in self.stats:
                self.stats[L]["tries"] += 1
        if show_robot:
            self.robot_cmd("ILYHOLD" if L == "ILY" else f"SHOW {L}")
        else:
            self.robot_cmd("OPEN")

    def mastered(self) -> list[str]:
        """Curriculum letters the learner has passed at least once."""
        return [L for L in CURRICULUM if self.stats[L]["passed"] > 0]

    # ---------------------------------------------------------- actions (all return a sentence to speak)
    def teach(self, L: str) -> str:
        """Hold a letter on the robot and explain how to form it."""
        if L in WORDS_ONLY:
            return self.say(f"The robot can't make {L}, so here it is in words: {WORDS_ONLY[L]}")
        if L not in CONTENT:
            return self.say("I can teach letters A to Z. Which one?")
        self._set_target(L, "teach")
        how, tip, _ = CONTENT[L]
        name = "I love you" if L == "ILY" else L
        return self.say(f"This is {name}. {how} {tip}")

    def next_letter(self) -> str:
        """Teach the next unpassed curriculum letter (or a random review)."""
        todo = [L for L in CURRICULUM if self.stats[L]["passed"] == 0]
        L = todo[0] if todo else random.choice(CURRICULUM)
        return self.teach(L)

    def hint(self, live_fix: str | None = None) -> str:
        """Spoken tip for the current target, optionally prefixed with a live camera fix."""
        L = self.target
        if L not in CONTENT:
            return self.say("Ask me for a letter first.")
        _, tip, mistake = CONTENT[L]
        return self.say(f"{live_fix + ' ' if live_fix else ''}{mistake} Remember: {tip}")

    def word_practice(self, word: str) -> str:
        """Sign a word letter by letter; advances itself after each pass."""
        w = "".join(c for c in word.upper() if c in ALLOWED)
        if not w:
            w = random.choice(WORDS)
        with self.lock:
            self.word, self.idx = w, 0
        self._set_target(w[0], "word")
        skipped = "".join(c for c in word.upper() if c.isalpha() and c not in ALLOWED)
        extra = f" I skipped {', '.join(skipped)}, the robot can't form those." if skipped else ""
        return self.say(f"Let's sign {w}, letter by letter. First, {w[0]}: {CONTENT[w[0]][0]}{extra}")

    def quiz(self) -> str:
        """Robot signs a hidden letter; learner guesses via guess()."""
        L = random.choice(CURRICULUM)
        with self.lock:
            self.quiz_answer = L
        self._set_target(L, "quiz", show_robot=True, show_answer=False)
        return self.say("Quiz time. What letter is the robot making?")

    def guess(self, g: str) -> str:
        """Score a quiz guess; reveals the answer either way."""
        with self.lock:
            ans = self.quiz_answer
        if not ans:
            return self.say("There's no quiz running. Say 'quiz me' to start one.")
        if g == ans:
            with self.lock:
                self.quiz_answer = None
                self.show_answer = True
                self.streak += 1; self.total += 1
                self.best_streak = max(self.best_streak, self.streak)
                self.flash_until = time.time() + 1.2
            return self.say(f"Yes, it's {ans}! Now you make it.")
        with self.lock:
            self.streak = 0
            self.quiz_answer = None
            self.show_answer = True
        return self.say(f"Close, but it's {ans}. {CONTENT[ans][0]}")

    def memory(self, L: str | None = None) -> str:
        """Learner signs from memory; robot stays open/hidden until they pass."""
        L = L if L in CONTENT else random.choice(self.mastered() or CURRICULUM)
        self._set_target(L, "memory", show_robot=False, show_answer=True)
        return self.say(f"From memory: sign {L}. The robot won't help this time.")

    def free(self) -> str:
        """Relax the robot; learner can sign anything for /see."""
        with self.lock:
            self.mode, self.target, self.word = "free", None, ""
            self.instance += 1
        self.robot_cmd("OPEN")
        return self.say("Free mode. Sign any letter and I'll tell you what I see.")

    def progress(self) -> str:
        """Spoken summary of letters passed and best streak."""
        m = self.mastered()
        if not m:
            return self.say("No letters passed yet. Say 'next' to start with L.")
        return self.say(f"You've passed {len(m)} of {len(CURRICULUM)} letters: {', '.join(m)}. "
                        f"Best streak: {self.best_streak}.")

    # ---------------------------------------------------------- called by the camera loop
    def on_pass(self, L: str, now: float) -> bool:
        """The learner held the right shape long enough. Returns True if this is a new pass."""
        with self.lock:
            if self.passed_instance == self.instance or L != self.target:
                return False
            self.passed_instance = self.instance
            st = self.stats.get(L)
            if st is not None:
                st["passed"] += 1
                dt = round(now - self.target_since, 1)
                st["best"] = dt if st["best"] is None else min(st["best"], dt)
            self.streak += 1; self.total += 1
            self.best_streak = max(self.best_streak, self.streak)
            self.flash_until = now + 1.2
            if self.mode == "quiz":
                self.quiz_answer = None
                self.show_answer = True
            if self.mode == "word":
                if self.idx + 1 < len(self.word):
                    self.pending_advance = now + ADVANCE_DELAY
                else:
                    self.celebrate_until = now + 3.0
                    self.say(f"You spelled {self.word}!")
            elif self.mode == "memory":
                self.robot_cmd(f"SHOW {L}")          # reveal: the robot agrees
            self.events.append({"t": now, "pass": L})
            return True

    def tick(self, now: float) -> None:
        """Advance word practice after the short 'Correct!' pause."""
        with self.lock:
            if self.pending_advance and now >= self.pending_advance and self.mode == "word":
                self.pending_advance = None
                self.idx += 1
                L = self.word[self.idx]
            else:
                return
        self._set_target(L, "word")

    def _helpful(self) -> bool:
        """Show the how-to text? Not while it would give away a quiz / memory answer."""
        if self.target not in CONTENT or not self.show_answer:
            return False
        return self.mode != "memory" or self.passed_instance == self.instance

    def snapshot(self) -> dict[str, Any]:
        """Thread-safe view of session state for the window and API helpers."""
        with self.lock:
            return {
                "mode": self.mode, "target": self.target, "show_answer": self.show_answer,
                "passed": self.passed_instance == self.instance and self.target is not None,
                "word": self.word, "idx": self.idx, "streak": self.streak,
                "best_streak": self.best_streak, "total": self.total,
                "mastered": self.mastered(), "curriculum": CURRICULUM,
                "captions": list(self.captions), "flash": time.time() < self.flash_until,
                "celebrate": time.time() < self.celebrate_until,
                "how": CONTENT[self.target][0] if self._helpful() else "",
                "tip": CONTENT[self.target][1] if self._helpful() else "",
            }
