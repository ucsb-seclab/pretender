#include "mbed.h"

InterruptIn button(USER_BUTTON);

DigitalOut led(LED1);

double delay = 0.5; // 500 ms

void pressed()
{
    delay = 0.1; // 100 ms
}

void released()
{
    delay = 0.5; // 500 ms
}

int main()
{
    // Assign functions to button
    button.fall(&pressed);
    button.rise(&released);

    while (1) {
        led = !led;
        wait(delay);
    }
}
