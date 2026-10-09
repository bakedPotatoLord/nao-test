#include <Arduino.h>


#include <Arduino/Stepper.h>

#define stepperpin1_1 3;
#define stepperpin1_1 4;
#define stepperpin1_1 5;
#define stepperpin1_1 6;

#define stepperpin1_1 7;
#define stepperpin1_1 8;
#define stepperpin1_1 9;
#define stepperpin1_1 10;

#define smallGearTeeth 16;

#define bigGearTeeth 20;

Stepper stepper1(200, stepperpin1_1, stepperpin1_2, stepperpin1_3, stepperpin1_4);

Stepper stepper2(200, stepperpin2_1, stepperpin2_2, stepperpin2_3, stepperpin2_4);

void setup() {
  // put your setup code here, to run once:
  int result = myFunction(2, 3);
}

void loop() {
  // put your main code here, to run repeatedly:
}

// put function definitions here:
int myFunction(int x, int y) {
  return x + y;
}