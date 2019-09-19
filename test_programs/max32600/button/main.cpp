#include "mbed.h"

InterruptIn button(BUTTON1);

DigitalOut led(LED1);

double delay = 0.5; // 500 ms

void pressed()
{
    led = 1;
}

void released()
{
    led = 0;
}

int main()
{
    // Assign functions to button
    button.fall(&pressed);
    button.rise(&released);

    while (1) {
    }
}
