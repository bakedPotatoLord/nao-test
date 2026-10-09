#include <Arduino.h>


#include <Stepper.h>

#define stepperpin1_1 2
#define stepperpin1_2 3
#define stepperpin1_3 4
#define stepperpin1_4 5

#define stepperpin2_1 7
#define stepperpin2_2 8
#define stepperpin2_3 9
#define stepperpin2_4 10

#define smallGearTeeth 16;

#define bigGearTeeth 20;

Stepper stepper1(200, stepperpin1_1, stepperpin1_2, stepperpin1_3, stepperpin1_4);

Stepper stepper2(200, stepperpin2_1, stepperpin2_2, stepperpin2_3, stepperpin2_4);

void setup() {
  // put your setup code here, to run once:
  stepper1.setSpeed(60);
  stepper2.setSpeed(60);
}

void loop() {
  // put your main code here, to run repeatedly:
  stepper1.step(3);
  delay(100);
  stepper1.step(-3);
  delay(100);
}

