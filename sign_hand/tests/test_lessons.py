"""Offline tests for Session teaching modes (fake robot send)."""
import random
import time

from lessons import ADVANCE_DELAY, CONTENT, Session


def _session():
    cmds = []
    return Session(lambda line: cmds.append(line)), cmds


def test_teach_and_next():
    s, cmds = _session()
    say = s.teach("L")
    assert "L" in say
    assert cmds[-1] == "SHOW L"
    assert s.mode == "teach" and s.target == "L"
    # words-only letter
    say = s.teach("G")
    assert "can't make" in say.lower() or "words" in say.lower()
    # next picks first unpassed curriculum letter
    s2, _ = _session()
    say = s2.next_letter()
    assert s2.target == "L"
    assert "L" in say or "Thumb" in say or "index" in say.lower()


def test_hint():
    s, _ = _session()
    assert "letter" in s.hint().lower()
    s.teach("Y")
    h = s.hint("Curl your index.")
    assert "Curl your index." in h
    assert "shaka" in h.lower() or "Remember" in h


def test_quiz_never_leaks_answer():
    s, cmds = _session()
    random.seed(1)
    say = s.quiz()
    ans = s.quiz_answer
    assert ans is not None
    assert ans in CONTENT
    assert ans not in say
    assert "Quiz" in say
    snap = s.snapshot()
    assert snap["show_answer"] is False
    assert snap["how"] == ""
    assert snap["tip"] == ""
    assert snap["mode"] == "quiz"
    assert cmds[-1] == f"SHOW {ans}"
    # wrong guess reveals answer in the spoken reply (after the quiz ends)
    wrong = next(L for L in CONTENT if L != ans and len(L) == 1)
    g = s.guess(wrong)
    assert ans in g
    assert s.quiz_answer is None


def test_guess_correct():
    s, _ = _session()
    random.seed(2)
    s.quiz()
    ans = s.quiz_answer
    say = s.guess(ans)
    assert "Yes" in say and ans in say
    assert s.show_answer is True
    assert s.quiz_answer is None


def test_memory_hides_robot_until_passed():
    s, cmds = _session()
    say = s.memory("B")
    assert "memory" in say.lower() and "B" in say
    assert cmds[-1] == "OPEN"
    assert s.mode == "memory" and s.target == "B"
    snap = s.snapshot()
    # robot stays hidden until pass (view uses mode==memory and not passed)
    assert not (snap["mode"] == "memory" and snap["passed"])
    now = time.time()
    assert s.on_pass("B", now) is True
    assert f"SHOW B" in cmds
    assert s.snapshot()["passed"] is True


def test_word_practice_auto_advances_after_on_pass():
    s, cmds = _session()
    say = s.word_practice("FOOD")
    assert s.word == "FOOD" and s.idx == 0 and s.target == "F"
    assert "FOOD" in say and cmds[-1] == "SHOW F"
    now = time.time()
    assert s.on_pass("F", now) is True
    assert s.pending_advance is not None
    s.tick(now + ADVANCE_DELAY + 0.05)
    assert s.idx == 1 and s.target == "O"
    assert cmds[-1] == "SHOW O"
    # finish the word
    for i, L in enumerate("OOD", start=1):
        now = time.time()
        assert s.on_pass(L, now)
        if i < 3:
            s.tick(now + ADVANCE_DELAY + 0.05)
    assert "spelled FOOD" in s.captions[-1]["text"].lower() or "FOOD" in s.captions[-1]["text"]
