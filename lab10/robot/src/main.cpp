
#include <Arduino.h>
#include <AccelStepper.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
// #include <cstdlib>

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

// ---------------- MOTION CONFIGURATION ----------------

// Calibrate these for your actual differential and gearing.
// These are logical axis steps per degree of head movement.
constexpr float ROT_STEPS_PER_DEG = 10.0f;
constexpr float TILT_STEPS_PER_DEG = 10.0f;

// Permitted head angles, in degrees.
constexpr float ROT_MIN_DEG = -90.0f;
constexpr float ROT_MAX_DEG =  90.0f;

constexpr float TILT_MIN_DEG = -10.0f;
constexpr float TILT_MAX_DEG =  10.0f;

// Maximum normal motion speed, in motor steps/second.
constexpr float MAX_SPEED = 400.0f;
constexpr float ACCELERATION = 200.0f;

// ---------------- HOMING CONFIGURATION ----------------

// Hall sensor activates when its analog reading crosses
// this threshold. Adjust after observing analogRead(A0).
constexpr int ROT_HALL_THRESHOLD = 300;

// true: sensor active when reading > threshold.
// false: sensor active when reading < threshold.
constexpr bool ROT_HALL_ACTIVE_ABOVE_THRESHOLD = false;

// Homing speed in motor steps/second.
// Negative rotation speed means seek in the negative direction.
constexpr float ROT_HOME_SPEED = -30.0f;
constexpr float TILT_HOME_SPEED = -30.0f;

// Maximum travel allowed while seeking each home sensor.
constexpr long MAX_HOME_TRAVEL = 5000;

constexpr unsigned long SERIAL_BAUD = 9600;

// ---------------- STEPPERS ----------------

// Standard four-wire step sequence.
// Typical ULN2003/28BYJ-48 wiring uses IN1, IN3, IN2, IN4.
AccelStepper motor1(
    AccelStepper::FULL4WIRE,
    M1_PIN_1, M1_PIN_3, M1_PIN_2, M1_PIN_4
);

AccelStepper motor2(
    AccelStepper::FULL4WIRE,
    M2_PIN_1, M2_PIN_3, M2_PIN_2, M2_PIN_4
);

// ---------------- CONTROLLER STATE ----------------

enum ControllerState {
    HOME_ROTATION,
    HOME_TILT,
    READY,
    FAULT
};

ControllerState state = HOME_ROTATION;

enum AngleMode {
    DEGREES,
    RADIANS
};

AngleMode angleMode = DEGREES;

// Physical motor coordinates corresponding to logical zero.
// These allow the axes to be zeroed independently.
float rotationOffset = 0.0f;
float tiltOffset = 0.0f;

long homeStart1 = 0;
long homeStart2 = 0;

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
    return digitalRead(TILT_LIMIT_PIN) == LOW;
}

// ---------------- POSITION MAPPING ----------------

// Convert physical motor coordinates into logical axis coordinates.
// Differential mapping:
//   rotation = (motor1 + motor2) / 2
//   tilt     = (motor1 - motor2) / 2
//
// Offsets account for independently homed axes.

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

// ---------------- MOTION COMMANDS ----------------

void moveToAngles(float rotationDeg, float tiltDeg) {
    // Validate rather than silently clamp requested positions.
    if (rotationDeg < ROT_MIN_DEG ||
        rotationDeg > ROT_MAX_DEG) {
        Serial.println(F("ERR: rotation target outside limits"));
        return;
    }

    if (tiltDeg < TILT_MIN_DEG ||
        tiltDeg > TILT_MAX_DEG) {
        Serial.println(F("ERR: tilt target outside limits"));
        return;
    }

    // Convert logical angles into logical step coordinates.
    float r = rotationDeg * ROT_STEPS_PER_DEG;
    float t = tiltDeg * TILT_STEPS_PER_DEG;

    // Invert the differential mapping to obtain motor targets.
    long target1 = lroundf(rotationOffset + r + tiltOffset + t);
    long target2 = lroundf(rotationOffset + r - tiltOffset - t);

    motor1.moveTo(target1);
    motor2.moveTo(target2);

    Serial.print(F("Target rotation: "));
    Serial.print(rotationDeg, 2);
    Serial.print(F(" deg, tilt: "));
    Serial.print(tiltDeg, 2);
    Serial.println(F(" deg"));
}

float inputToDegrees(float value) {
    return angleMode == RADIANS
        ? value * 180.0f / PI
        : value;
}

void commandAxis(const char* axis,
                 const char* operation,
                 float value) {
    if (state != READY) {
        Serial.println(F("ERR: axes not homed and ready"));
        return;
    }

    float rotation = currentRotationDeg();
    float tilt = currentTiltDeg();

    float angle = inputToDegrees(value);

    if (strcmp(axis, "rot") == 0) {
        if (strcmp(operation, "abs") == 0) {
            rotation = angle;
        } else if (strcmp(operation, "rel") == 0) {
            rotation += angle;
        } else {
            Serial.println(F("ERR: use rot abs/rel <value>"));
            return;
        }
    } else if (strcmp(axis, "tilt") == 0) {
        if (strcmp(operation, "abs") == 0) {
            tilt = angle;
        } else if (strcmp(operation, "rel") == 0) {
            tilt += angle;
        } else {
            Serial.println(F("ERR: use tilt abs/rel <value>"));
            return;
        }
    } else {
        Serial.println(F("ERR: unknown axis"));
        return;
    }

    moveToAngles(rotation, tilt);
}

// ---------------- HOMING ----------------

void beginRotationHoming() {
    state = HOME_ROTATION;

    homeStart1 = motor1.currentPosition();
    homeStart2 = motor2.currentPosition();

    motor1.setSpeed(ROT_HOME_SPEED);
    motor2.setSpeed(ROT_HOME_SPEED);

    Serial.println(F("Homing rotation..."));
}

void beginTiltHoming() {
    state = HOME_TILT;

    homeStart1 = motor1.currentPosition();
    homeStart2 = motor2.currentPosition();

    // Opposite motor directions move the tilt axis.
    motor1.setSpeed(TILT_HOME_SPEED);
    motor2.setSpeed(-TILT_HOME_SPEED);

    Serial.println(F("Homing tilt..."));
}

bool exceededHomeTravel() {
    long d1 = labs(motor1.currentPosition() - homeStart1);
    long d2 = labs(motor2.currentPosition() - homeStart2);

    return d1 > MAX_HOME_TRAVEL || d2 > MAX_HOME_TRAVEL;
}

void updateHoming() {
    if (state == HOME_ROTATION) {
        if (rotationHomeActive()) {
            // Establish rotation zero. This is the initial reference
            // for both motor coordinates.
            motor1.setCurrentPosition(0);
            motor2.setCurrentPosition(0);

            rotationOffset = 0.0f;
            tiltOffset = 0.0f;

            beginTiltHoming();
            return;
        }

        if (exceededHomeTravel()) {
            state = FAULT;
            Serial.println(F("FAULT: rotation home not found"));
            return;
        }

        // Rotation-only motion: both motors move together.
        motor1.runSpeed();
        motor2.runSpeed();
        return;
    }

    if (state == HOME_TILT) {
        if (tiltHomeActive()) {
            // Keep rotation zero where it is. Record the tilt offset
            // at the current physical motor positions.
            tiltOffset =
                ((float)motor1.currentPosition()
               - (float)motor2.currentPosition()) / 2.0f;

            state = READY;

            motor1.setMaxSpeed(MAX_SPEED);
            motor2.setMaxSpeed(MAX_SPEED);

            motor1.setAcceleration(ACCELERATION);
            motor2.setAcceleration(ACCELERATION);

            Serial.println(F("Homing complete. Ready."));
            Serial.println(F("Commands: rot/tilt abs/rel <value>"));
            Serial.println(F("          mode deg | mode rad"));
            return;
        }

        if (exceededHomeTravel()) {
            state = FAULT;
            Serial.println(F("FAULT: tilt home not found"));
            return;
        }

        // Tilt-only motion: motors move in opposite directions.
        motor1.runSpeed();
        motor2.runSpeed();
    }
}

// ---------------- SERIAL INTERFACE ----------------

void processCommand(char* line) {
    char* command = strtok(line, " \t\r\n");

    if (command == nullptr) return;

    if (strcmp(command, "mode") == 0) {
        char* mode = strtok(nullptr, " \t\r\n");

        if (mode == nullptr) {
            Serial.println(F("ERR: use mode deg or mode rad"));
            return;
        }

        if (strcmp(mode, "deg") == 0) {
            angleMode = DEGREES;
            Serial.println(F("Angle mode: degrees"));
        } else if (strcmp(mode, "rad") == 0) {
            angleMode = RADIANS;
            Serial.println(F("Angle mode: radians"));
        } else {
            Serial.println(F("ERR: use mode deg or mode rad"));
        }

        return;
    }

    if (strcmp(command, "home") == 0) {
        if (state == HOME_ROTATION || state == HOME_TILT) {
            Serial.println(F("Already homing"));
            return;
        }

        // Re-home from the current physical location.
        beginRotationHoming();
        return;
    }

    char* operation = strtok(nullptr, " \t\r\n");
    char* valueText = strtok(nullptr, " \t\r\n");
    char* extra = strtok(nullptr, " \t\r\n");

    if (operation == nullptr || valueText == nullptr || extra != nullptr) {
        Serial.println(F("ERR: use rot abs 10 or tilt rel -5"));
        return;
    }

    char* endPtr;
    float value = strtod(valueText, &endPtr);

    if (*valueText == '\0' || *endPtr != '\0' || !isfinite(value)) {
        Serial.println(F("ERR: invalid number"));
        return;
    }

    commandAxis(command, operation, value);
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
        } else if (serialLength < sizeof(serialBuffer) - 1) {
            serialBuffer[serialLength++] = c;
        } else {
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

    motor1.setMaxSpeed(MAX_SPEED);
    motor2.setMaxSpeed(MAX_SPEED);

    motor1.setAcceleration(ACCELERATION);
    motor2.setAcceleration(ACCELERATION);

    Serial.println(F("Robot head controller starting"));
    Serial.println(F("Startup homing begins automatically"));

    beginRotationHoming();
}

void loop() {
    readSerial();

    if (state == HOME_ROTATION || state == HOME_TILT) {
        updateHoming();
    } else if (state == READY) {
        // Nonblocking: both motors advance as needed.
        motor1.run();
        motor2.run();
    }

    // Serial.println(analogRead(ROT_HALL_PIN));
}
