#include "mbed.h"
void led_switch(void);
Ticker time_up;
DigitalOut myled(LED1);


void led_switch() {
    myled=!myled;
}


int main(){
    time_up.attach(&led_switch, 0.5);
    while(true) {
        //wait(1);
    }
}
