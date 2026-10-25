
#include <Arduino.h>
#include <AccelStepper.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// ---------------- PIN CONFIGURATION ----------------

#define M1_PIN_1 2
#define M1_PIN_2 3
#define M1_PIN_3 4
#define M1_PIN_4 5

#define M2_PIN_1 6
#define M2_PIN_2 7
#define M2_PIN_3 8
#define M2_PIN_4 9

#define ROT_HALL_PIN A0
#define TILT_LIMIT_PIN 10

constexpr unsigned long SERIAL_BAUD = 9600;

// ---------------- MECHANICAL CONFIGURATION ----------------

// Logical head-axis steps per degree.
// Calibrate for your differential and gearing.
constexpr float ROT_STEPS_PER_DEG = 10.0f;
constexpr float TILT_STEPS_PER_DEG = 10.0f;

// Mechanical safety limits, in degrees.
constexpr float ROT_MIN_DEG = -90.0f;
constexpr float ROT_MAX_DEG =  90.0f;

constexpr float TILT_MIN_DEG = -5.0f;
constexpr float TILT_MAX_DEG =  5.0f;

// ---------------- HOMING CONFIGURATION ----------------

constexpr int ROT_HALL_THRESHOLD = 300;
constexpr bool ROT_HALL_ACTIVE_ABOVE_THRESHOLD = false;

constexpr float ROT_HOME_SPEED = -30.0f;
constexpr float TILT_HOME_SPEED = -30.0f;

constexpr long MAX_HOME_TRAVEL = 5000;

// ---------------- STEPPERS ----------------

// Typical ULN2003 / 28BYJ-48 pin sequence.
AccelStepper motor1(
    AccelStepper::FULL4WIRE,
    M1_PIN_1, M1_PIN_3, M1_PIN_2, M1_PIN_4
);

AccelStepper motor2(
    AccelStepper::FULL4WIRE,
    M2_PIN_1, M2_PIN_3, M2_PIN_2, M2_PIN_4
);

// ---------------- EMOTION STATES ----------------

enum EmoteState {
    EMOTE_BREATHE,
    EMOTE_NOD_NO,
    EMOTE_NOD_YES,
    EMOTE_LOOK_LEFT,
    EMOTE_LOOK_RIGHT,
    EMOTE_LOOK_UP_RIGHT,
    EMOTE_LOOK_DOWN,
};

enum ControllerState {
    HOME_ROTATION,
    HOME_TILT,
    READY,
    FAULT
};

ControllerState controllerState = HOME_ROTATION;
EmoteState currentEmote = EMOTE_BREATHE;

// ---------------- EMOTION CONFIGURATION ----------------

// Each range is the maximum angle away from the neutral pose.
// Speed is in physical motor steps per second.
// Acceleration is in physical motor steps per second squared.
// Pause is the dwell time at each pose, in milliseconds.

struct EmoteConfig {
    float rotationRange;
    float tiltRange;
    float speed;
    float acceleration;
    unsigned long pauseMs;
};

EmoteConfig emoteConfigs[] = {
    // Rotation range, tilt range, speed, accel, pause

    // Gentle, continuous breathing
    {  0.0f, 1.0f, 30.0f, 50.0f, 1000 },

    // Shake head side to side
    {  8.0f, 0.0f, 180.0f, 180.0f, 180 },

    // Nod head up and down
    {  0.0f, 2.5f, 140.0f, 140.0f, 250 },

    // Turn and hold gaze left
    { 45.0f, 0.0f, 300.0f, 180.0f, 0 },

    // Turn and hold gaze right
    { 45.0f, 0.0f, 300.0f, 180.0f, 0 },

    // Look up and twist right, then hold until another command.
    { 30.0f, 4.0f, 180.0f, 140.0f, 0 },

    // Look down, then hold until another command.
    // tiltRange is a positive magnitude; the pose applies the minus sign.
    {  0.0f, 4.0f, 140.0f, 140.0f, 0 }
};

// ---------------- POSITION STATE ----------------

// Motor coordinates representing the logical neutral pose.
float rotationOffset = 0.0f;
float tiltOffset = 0.0f;

long homeStart1 = 0;
long homeStart2 = 0;

// ---------------- EMOTION SEQUENCER ----------------

unsigned int emotePhase = 0;
bool waitingAtPose = false;
unsigned long poseReachedAt = 0;

// Serial command buffer
char serialBuffer[64];
size_t serialLength = 0;

// ---------------- SENSOR HELPERS ----------------

bool rotationHomeActive() {
    int reading = analogRead(ROT_HALL_PIN);

    if (ROT_HALL_ACTIVE_ABOVE_THRESHOLD) {
        return reading > ROT_HALL_THRESHOLD;
    }

    return reading < ROT_HALL_THRESHOLD;
}

bool tiltHomeActive() {
    // INPUT_PULLUP: switch connects pin to GND when pressed.
    return true;
}

// ---------------- DIFFERENTIAL MAPPING ----------------

// rotation = (motor1 + motor2) / 2
// tilt     = (motor1 - motor2) / 2

float rotationPositionSteps() {
    return ((float)motor1.currentPosition()
          + (float)motor2.currentPosition()) / 2.0f
          - rotationOffset;
}

float tiltPositionSteps() {
    return ((float)motor1.currentPosition()
          - (float)motor2.currentPosition()) / 2.0f
          - tiltOffset;
}

float currentRotationDeg() {
    return rotationPositionSteps() / ROT_STEPS_PER_DEG;
}

float currentTiltDeg() {
    return tiltPositionSteps() / TILT_STEPS_PER_DEG;
}

// ---------------- POSE CONTROL ----------------

void moveToPose(float rotationDeg, float tiltDeg) {
    // Never command a pose outside the configured safety limits.
    rotationDeg = constrain(
        rotationDeg, ROT_MIN_DEG, ROT_MAX_DEG
    );

    tiltDeg = constrain(
        tiltDeg, TILT_MIN_DEG, TILT_MAX_DEG
    );

    float r = rotationDeg * ROT_STEPS_PER_DEG;
    float t = tiltDeg * TILT_STEPS_PER_DEG;

    // Convert logical rotation/tilt into physical motor positions.
    long target1 = lroundf(
        rotationOffset + r + tiltOffset + t
    );

    long target2 = lroundf(
        rotationOffset + r - tiltOffset - t
    );

    motor1.moveTo(target1);
    motor2.moveTo(target2);
}

bool poseReached() {
    return motor1.distanceToGo() == 0 &&
           motor2.distanceToGo() == 0;
}

// Return the pose for the current phase of an emotion.
void issueEmotePose() {
    const EmoteConfig &cfg = emoteConfigs[currentEmote];

    float r = cfg.rotationRange;
    float t = cfg.tiltRange;

    switch (currentEmote) {
        case EMOTE_BREATHE:
            // Gentle alternating tilt, like a breathing motion.
            moveToPose(
                0,
                (emotePhase % 2 == 0) ? t : -t
            );
            break;

        case EMOTE_NOD_NO:
            // Shake left, right, return to center.
            switch (emotePhase % 3) {
                case 0: moveToPose(-r, 0); break;
                case 1: moveToPose( r, 0); break;
                case 2: moveToPose( 0, 0); break;
            }
            break;

        case EMOTE_NOD_YES:
            // Nod down, up, return to center.
            switch (emotePhase % 3) {
                case 0: moveToPose(0, -t); break;
                case 1: moveToPose(0,  t); break;
                case 2: moveToPose(0,  0); break;
            }
            break;

        case EMOTE_LOOK_LEFT:
            moveToPose(-r, 0);
            break;

        case EMOTE_LOOK_RIGHT:
            moveToPose(r, 0);
            break;

        case EMOTE_LOOK_UP_RIGHT:
            moveToPose(r, t);
            break;

        case EMOTE_LOOK_DOWN:
            moveToPose(0, -t);
            break;
    }
}

void setEmote(EmoteState emote) {
    if (controllerState != READY) {
        Serial.println(F("ERR: home the robot first"));
        return;
    }

    currentEmote = emote;
    emotePhase = 0;
    waitingAtPose = false;

    const EmoteConfig &cfg = emoteConfigs[currentEmote];

    motor1.setMaxSpeed(cfg.speed);
    motor2.setMaxSpeed(cfg.speed);

    motor1.setAcceleration(cfg.acceleration);
    motor2.setAcceleration(cfg.acceleration);

    issueEmotePose();

    Serial.print(F("Emote: "));

    switch (emote) {
        case EMOTE_BREATHE:
            Serial.println(F("EMOTE_BREATHE"));
            break;
        case EMOTE_NOD_NO:
            Serial.println(F("EMOTE_NOD_NO"));
            break;
        case EMOTE_NOD_YES:
            Serial.println(F("EMOTE_NOD_YES"));
            break;
        case EMOTE_LOOK_LEFT:
            Serial.println(F("EMOTE_LOOK_LEFT"));
            break;
        case EMOTE_LOOK_RIGHT:
            Serial.println(F("EMOTE_LOOK_RIGHT"));
            break;
        case EMOTE_LOOK_UP_RIGHT:
            Serial.println(F("EMOTE_LOOK_UP_RIGHT"));
            break;
        case EMOTE_LOOK_DOWN:
            Serial.println(F("EMOTE_LOOK_DOWN"));
            break;
    }
}

bool isHoldingGaze() {
    return currentEmote == EMOTE_LOOK_LEFT ||
           currentEmote == EMOTE_LOOK_RIGHT ||
           currentEmote == EMOTE_LOOK_UP_RIGHT;
}

void updateEmote() {
    if (!waitingAtPose) {
        if (poseReached()) {
            waitingAtPose = true;
            poseReachedAt = millis();
        }
        return;
    }

    // A look emotion holds its final pose until another command.
    if (isHoldingGaze()) {
        return;
    }

    const EmoteConfig &cfg = emoteConfigs[currentEmote];

    if (millis() - poseReachedAt >= cfg.pauseMs) {
        emotePhase++;
        waitingAtPose = false;
        issueEmotePose();
    }
}

// ---------------- HOMING ----------------

void beginRotationHoming() {
    controllerState = HOME_ROTATION;

    homeStart1 = motor1.currentPosition();
    homeStart2 = motor2.currentPosition();

    motor1.setSpeed(ROT_HOME_SPEED);
    motor2.setSpeed(ROT_HOME_SPEED);

    Serial.println(F("Homing rotation..."));
}

void beginTiltHoming() {
    controllerState = HOME_TILT;

    homeStart1 = motor1.currentPosition();
    homeStart2 = motor2.currentPosition();

    motor1.setSpeed(TILT_HOME_SPEED);
    motor2.setSpeed(-TILT_HOME_SPEED);

    Serial.println(F("Homing tilt..."));
}

bool exceededHomeTravel() {
    long d1 = labs(motor1.currentPosition() - homeStart1);
    long d2 = labs(motor2.currentPosition() - homeStart2);

    return d1 > MAX_HOME_TRAVEL ||
           d2 > MAX_HOME_TRAVEL;
}

void updateHoming() {
    if (controllerState == HOME_ROTATION) {
        if (rotationHomeActive()) {
            // Establish the rotation reference.
            motor1.setCurrentPosition(0);
            motor2.setCurrentPosition(0);

            rotationOffset = 0.0f;
            tiltOffset = 0.0f;

            beginTiltHoming();
            return;
        }

        if (exceededHomeTravel()) {
            controllerState = FAULT;
            Serial.println(F("FAULT: rotation home not found"));
            return;
        }

        motor1.runSpeed();
        motor2.runSpeed();
        return;
    }

    if (controllerState == HOME_TILT) {
        if (tiltHomeActive()) {
            // Record the tilt zero without changing rotation zero.
            tiltOffset =
                ((float)motor1.currentPosition()
               - (float)motor2.currentPosition()) / 2.0f;

            controllerState = READY;

            motor1.setMaxSpeed(200.0f);
            motor2.setMaxSpeed(200.0f);
            motor1.setAcceleration(150.0f);
            motor2.setAcceleration(150.0f);

            Serial.println(F("Homing complete."));
            Serial.println(F("Send an emote name or 'home'."));
            Serial.println(F("Default emotion: EMOTE_BREATHE"));

            setEmote(EMOTE_BREATHE);
            return;
        }

        if (exceededHomeTravel()) {
            controllerState = FAULT;
            Serial.println(F("FAULT: tilt home not found"));
            return;
        }

        motor1.runSpeed();
        motor2.runSpeed();
    }
}

// ---------------- SERIAL INTERFACE ----------------

void processCommand(char* line) {
    char* command = strtok(line, " \t\r\n");

    if (command == nullptr) {
        return;
    }

    if (strcmp(command, "home") == 0) {
        if (controllerState == HOME_ROTATION ||
            controllerState == HOME_TILT) {
            Serial.println(F("Already homing"));
            return;
        }

        beginRotationHoming();
        return;
    }

    // Exact enum names plus convenient lowercase aliases.
    if (strcmp(command, "EMOTE_BREATHE") == 0 ||
        strcmp(command, "breathe") == 0) {
        setEmote(EMOTE_BREATHE);
    }
    else if (strcmp(command, "EMOTE_NOD_NO") == 0 ||
             strcmp(command, "nod_no") == 0) {
        setEmote(EMOTE_NOD_NO);
    }
    else if (strcmp(command, "EMOTE_NOD_YES") == 0 ||
             strcmp(command, "nod_yes") == 0) {
        setEmote(EMOTE_NOD_YES);
    }
    else if (strcmp(command, "EMOTE_LOOK_LEFT") == 0 ||
             strcmp(command, "look_left") == 0) {
        setEmote(EMOTE_LOOK_LEFT);
    }
    else if (strcmp(command, "EMOTE_LOOK_RIGHT") == 0 ||
             strcmp(command, "look_right") == 0) {
        setEmote(EMOTE_LOOK_RIGHT);
    }
    else if (strcmp(command, "EMOTE_LOOK_UP_RIGHT") == 0 ||
             strcmp(command, "look_up_right") == 0) {
        setEmote(EMOTE_LOOK_UP_RIGHT);
    }
    else if (strcmp(command, "EMOTE_LOOK_DOWN") == 0 ||
             strcmp(command, "look_down") == 0) {
        setEmote(EMOTE_LOOK_DOWN);
    }
    else {
        Serial.println(F("ERR: unknown emotion"));
        Serial.println(
            F("Use EMOTE_BREATHE, EMOTE_NOD_NO, EMOTE_NOD_YES,")
        );
        Serial.println(
            F("EMOTE_LOOK_LEFT, EMOTE_LOOK_RIGHT,")
        );
        Serial.println(
            F("EMOTE_LOOK_UP_RIGHT, EMOTE_LOOK_DOWN, or home")
        );
    }
}

void readSerial() {
    while (Serial.available() > 0) {
        char c = Serial.read();

        if (c == '\n' || c == '\r') {
            if (serialLength > 0) {
                serialBuffer[serialLength] = '\0';
                processCommand(serialBuffer);
                serialLength = 0;
            }
        }
        else if (serialLength < sizeof(serialBuffer) - 1) {
            serialBuffer[serialLength++] = c;
        }
        else {
            serialLength = 0;
            Serial.println(F("ERR: command too long"));
        }
    }
}

// ---------------- SETUP / LOOP ----------------

void setup() {
    Serial.begin(SERIAL_BAUD);

    pinMode(ROT_HALL_PIN, INPUT);
    pinMode(TILT_LIMIT_PIN, INPUT_PULLUP);

    motor1.setMaxSpeed(200.0f);
    motor2.setMaxSpeed(200.0f);

    motor1.setAcceleration(150.0f);
    motor2.setAcceleration(150.0f);

    Serial.println(F("Robot emotion controller starting"));
    beginRotationHoming();
}

void loop() {
    readSerial();

    if (controllerState == HOME_ROTATION ||
        controllerState == HOME_TILT) {
        updateHoming();
    }
    else if (controllerState == READY) {
        motor1.run();
        motor2.run();

        updateEmote();
    }
}