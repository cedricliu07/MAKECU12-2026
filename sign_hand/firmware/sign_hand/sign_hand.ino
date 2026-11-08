/*
  MakeCU sign-language hand — ESP32 firmware.
  Receives lines over USB serial (115200) from bridge.py:
    SHOW D            form one letter and HOLD it (teaching)
    ILYHOLD           hold "I love you"
    SPELL FOOD        fingerspell letter by letter
    ILY               "I love you" handshape
    OPEN              open hand
    SET t i m r p     raw finger curl 0..100 each (for calibration)
    ANGLE f deg       drive one finger's servo to a raw angle (find OPEN/CLOSED angles)

  Library: ESP32Servo (Arduino IDE: Library Manager → "ESP32Servo";
           PlatformIO: lib_deps = madhephaestus/ESP32Servo)

  POWER: servos on the 5 V supply (adjustable DC supply set to 5.0 V) via the
  power distribution node. Tie supply GND to ESP32 GND. Never power 5 servos from the ESP32.
*/
#include <ESP32Servo.h>

// Finger order everywhere: 0 thumb, 1 index, 2 middle, 3 ring, 4 pinky
const int PIN[5] = {18, 19, 21, 22, 23};

// --- CALIBRATE THESE (use ANGLE f deg) ---
// Servo angle when the finger is fully straight / fully curled.
// If a finger moves the wrong way, just swap its two numbers.
int OPEN_DEG[5]   = {  0,   0,   0,   0,   0};
int CLOSED_DEG[5] = {170, 170, 170, 170, 170};

const int HOLD_MS  = 1200;  // how long each letter is held
const int MOVE_MS  = 300;   // time to move between shapes
const int GAP_MS   = 250;   // brief relax between two identical letters (FOOD -> O, O)

Servo servo[5];
int cur[5] = {0, 0, 0, 0, 0};  // current curl 0..100

// Curl 0 = straight, 100 = fully curled.  {thumb, index, middle, ring, pinky}
// Starting guesses — tune by eye against an ASL chart.
struct Shape { char c; int f[5]; };
const Shape SHAPES[] = {
  {'A', { 20, 100, 100, 100, 100}},  // fist, thumb alongside
  {'B', {100,   0,   0,   0,   0}},  // flat hand, thumb across palm
  {'C', { 40,  50,  50,  50,  50}},  // curved C
  {'D', { 70,   0,  80,  80,  80}},  // index up, others touch thumb
  {'E', {100,  80,  80,  80,  80}},  // fingers bent over tucked thumb
  {'F', { 60,  70,   0,   0,   0}},  // thumb+index circle, 3 up
  {'I', {100, 100, 100, 100,   0}},  // pinky up
  {'L', {  0,   0, 100, 100, 100}},  // thumb + index L
  {'O', { 60,  65,  65,  65,  65}},  // all tips meet
  {'U', {100,   0,   0, 100, 100}},  // index + middle up together
  {'W', {100,   0,   0,   0, 100}},  // index + middle + ring up
  {'X', {100,  50, 100, 100, 100}},  // hooked index
  {'Y', {  0, 100, 100, 100,   0}},  // thumb + pinky out
};
const int ILY[5]  = {0, 0, 100, 100, 0};  // thumb + index + pinky
const int OPEN5[5] = {0, 0, 0, 0, 0};

int curlToDeg(int finger, int curl) {
  curl = constrain(curl, 0, 100);
  return OPEN_DEG[finger] + (long)(CLOSED_DEG[finger] - OPEN_DEG[finger]) * curl / 100;
}

void moveTo(const int target[5], int ms) {
  const int steps = max(1, ms / 15);
  int start[5];
  for (int f = 0; f < 5; f++) start[f] = cur[f];
  for (int s = 1; s <= steps; s++) {
    for (int f = 0; f < 5; f++) {
      int c = start[f] + (target[f] - start[f]) * s / steps;
      servo[f].write(curlToDeg(f, c));
    }
    delay(15);
  }
  for (int f = 0; f < 5; f++) cur[f] = target[f];
}

const Shape* findShape(char c) {
  for (auto &s : SHAPES) if (s.c == c) return &s;
  return nullptr;
}

void spell(const String &word) {
  char prev = 0;
  for (unsigned i = 0; i < word.length(); i++) {
    char c = toupper(word[i]);
    const Shape* s = findShape(c);
    if (!s) { Serial.printf("skip %c\n", c); continue; }
    if (c == prev) {                      // repeated letter: relax a bit so it reads as two
      int relaxed[5];
      for (int f = 0; f < 5; f++) relaxed[f] = cur[f] / 2;
      moveTo(relaxed, GAP_MS);
    }
    Serial.printf("letter %c\n", c);
    moveTo(s->f, MOVE_MS);
    delay(HOLD_MS);
    prev = c;
  }
  moveTo(OPEN5, MOVE_MS);
  Serial.println("done");
}

void setup() {
  Serial.begin(115200);
  for (int f = 0; f < 5; f++) {
    servo[f].setPeriodHertz(50);
    servo[f].attach(PIN[f], 500, 2400);
    servo[f].write(curlToDeg(f, 0));
  }
  Serial.println("sign hand ready");
}

void loop() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.startsWith("SPELL ")) {
    spell(line.substring(6));
  } else if (line == "ILY") {
    Serial.println("ILY");
    moveTo(ILY, MOVE_MS);
    delay(HOLD_MS * 2);
    moveTo(OPEN5, MOVE_MS);
    Serial.println("done");
  } else if (line.startsWith("SHOW ")) {      // teaching: hold one letter until the next command
    const Shape* s = findShape(toupper(line[5]));
    if (s) { moveTo(s->f, MOVE_MS); Serial.printf("showing %c\n", s->c); }
  } else if (line == "ILYHOLD") {
    moveTo(ILY, MOVE_MS);
    Serial.println("showing ILY");
  } else if (line == "OPEN") {
    moveTo(OPEN5, MOVE_MS);
  } else if (line.startsWith("SET ")) {
    int v[5];
    if (sscanf(line.c_str() + 4, "%d %d %d %d %d", &v[0], &v[1], &v[2], &v[3], &v[4]) == 5) moveTo(v, MOVE_MS);
  } else if (line.startsWith("ANGLE ")) {
    int f, deg;
    if (sscanf(line.c_str() + 6, "%d %d", &f, &deg) == 2 && f >= 0 && f < 5) {
      servo[f].write(constrain(deg, 0, 180));
      Serial.printf("finger %d -> %d deg\n", f, deg);
    }
  }
}
