
#include <Arduino.h>
#include <AccelStepper.h>

#define stepperpin1_1 2
#define stepperpin1_2 3
#define stepperpin1_3 4
#define stepperpin1_4 5

#define stepperpin2_1 6
#define stepperpin2_2 7
#define stepperpin2_3 8
#define stepperpin2_4 9

#define smallGearTeeth 16
#define bigGearTeeth 20

#define serialBaudRate 9600

// AccelStepper's 4-wire sequence expects pins in the order
// IN1, IN3, IN2, IN4 for typical 28BYJ-48 + ULN2003 wiring.
AccelStepper stepper1(
    AccelStepper::FULL4WIRE,
    stepperpin1_1, stepperpin1_3,
    stepperpin1_2, stepperpin1_4
);

AccelStepper stepper2(
    AccelStepper::FULL4WIRE,
    stepperpin2_1, stepperpin2_3,
    stepperpin2_2, stepperpin2_4
);

// Move both motors by independent relative step counts.
// Positive = forward; negative = backward.
// Returns after BOTH motors finish, while they move concurrently.
void moveBoth(long steps1, long steps2) {
    stepper1.move(steps1);
    stepper2.move(steps2);

    while (stepper1.distanceToGo() != 0 ||
           stepper2.distanceToGo() != 0) {
        stepper1.run();
        stepper2.run();
    }
}

// Both motors move forward.
void forwardBoth(long steps) {
    moveBoth(steps, steps);
}

// Both motors move backward.
void backwardBoth(long steps) {
    moveBoth(-steps, -steps);
}

// Motor 1 forward, motor 2 backward.
void oppositeForward(long steps) {
    moveBoth(steps, -steps);
}

// Motor 1 backward, motor 2 forward.
void oppositeBackward(long steps) {
    moveBoth(-steps, steps);
}

void setup() {
    Serial.begin(serialBaudRate);
    Serial.println("Hello world, starting");

    stepper1.setMaxSpeed(500);
    stepper2.setMaxSpeed(500);

    // Steps per second squared.
    stepper1.setAcceleration(200);
    stepper2.setAcceleration(200);
}

void loop() {
    forwardBoth(528);
    delay(200);

    backwardBoth(528);
    delay(200);

}
