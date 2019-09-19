#include "mbed.h"

Serial pc(SERIAL_TX, SERIAL_RX);
DigitalOut led(LED1);

void evil_read() {
	char buf[16];
	int i = 0;
	char c;
	pc.puts("Please enter the secret code:\r\n");
	while (1) {
        c = pc.getc();
		buf[i] = c;
		pc.putc(c);
		if (c == '\r') {
			buf[i] = 0;
			break;
		}
		i++;
	}
    pc.puts("Code accepted");
}

int main()
{
    while(1) {
        wait(0.25);
		char c = pc.getc(); // Read hyperterminal
		if (c == '0') {
            led = 0; // OFF
        }
        if (c == '1') {
            led = 1; // ON
		}
		if (c == '2') {
			while (1) {
				pc.puts("Self-destruct mode. Nuke the LED? (y/n)\r\n");
		    	c = pc.getc();
				if (c == 'y') {
					evil_read();
				}
				else if (c == 'n') {
					break;
				}
			}
		}
    }
}
