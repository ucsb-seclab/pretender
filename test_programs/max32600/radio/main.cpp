#include "mbed.h"

#define DEBUG 0

Serial rf(STDIO_UART_TX, STDIO_UART_RX);
DigitalOut led(LED1);
DigitalOut rf_config(D6); // Allegedly active-low
DigitalOut rf_en(D5); // Allegedly Active-low

DigitalOut lock_pin(D10); // Our "lock" relay

char cmd_get_config[] = {0xAA, 0xFA, 0xE1};
char cmd_reset[] = {0xAA, 0xFA, 0xF0};
char cmd_max_tx_power[] = {0xAA, 0xFA, 0x96, 0x07};

char* cmd_ok = "OK\r\n"; 

struct rf_config_t {
    uint32_t frequency;
    uint32_t data_rate;
    uint16_t bandwidth;
    uint8_t deviation;
    uint8_t tx_power;
    uint32_t baud_rate;
};


void die() {
    while (1);
}

void debug_print(char* s) {
	//pc.printf(s);
}

void rf_write_buf(char* buf, int len) {
    int i = 0;
    while (1) {
        if (rf.writable()) {
            rf.putc(buf[i]);
            i++;
            if (i == len) {
                break;
            }
        }
    }
}

int rf_read_buf(char* buf, int len) {
    int i = 0;
    char c;
    while (1) {
        if (rf.readable()) {
            c = rf.getc();
            buf[i] = c;
            i++;
            if (i == len) {
                break;
            }
        }
    }
    return i;
}

void get_rf_config() {
    char buf[16];
    struct rf_config_t* conf;
    rf_write_buf(cmd_get_config, 3);
    rf_read_buf(buf, 16);
    conf = (struct rf_config_t*) buf;
}

void reset_rf_config() {
    debug_print("Resetting RF Config...\r\n");
    char buf[4];
    rf_write_buf(cmd_reset, 4);
    rf_read_buf(buf, 4);
    debug_print(buf); // Should be 'OK\r\n'
    if (strncmp(buf, cmd_ok, 4) != 0) {
        debug_print("Failed to set TX power\r\n");
        die();
    }
}

void max_tx_power() {
    char buf[4];
    rf_write_buf(cmd_max_tx_power, 4);
    rf.gets(buf, 4);
    debug_print(buf); // Should be 'OK\r\n'
    if (!strncmp(buf, cmd_ok, 4)) {
        debug_print("Failed to set TX power\r\n");
        die();
    }
}

void configure_rf() {
    rf_config = 0; // LOW is for config mode
    reset_rf_config();
    //get_rf_config();
    max_tx_power();
    get_rf_config();   
    rf_config = 1;  
}

void unlock() {
    debug_print("Unlocked!\r\n");
    lock_pin = 1;
    wait(5);
    lock_pin = 0;
}

char the_pw[] = "UNLOCK";
void read_code() {
    char buf[16];
    char yes = 0xdd;
    char no = 0xcc;
    int i = 0;
    char c;
    while (1) {
        if (rf.readable()) {
            c = rf.getc();
            buf[i] = c;
            i++;
            if (c == 0) {
                break;
            }
        }
    }
    if (strcmp(buf, the_pw)) {
        rf_write_buf(&yes, 1);
        unlock();
    }
    else {
        debug_print("Got a bad code!\r\n");
        rf_write_buf(&no, 1);
    }
}

void set_code() {
	char buf[16];
	int i = 0;
	char c;
	char r = 0xdd;
	while (1) {
        if (rf.readable()) {
			c = rf.getc();
			buf[i] = c;
			if (c == '\n') {
				buf[i] = '\0';
				break;
			}
			i++;
		}
	}
	strcpy(the_pw, buf);
	rf.putc(r);
}

int main()
{
    
    char cmd;
	char r;
    debug_print("Setting up radio...\r\n");
    configure_rf();
    
    debug_print("Ready.");
    while(1) {
        if (rf.readable()) {
            cmd = rf.getc();
            switch (cmd) {
                case 0xBB:
                    read_code();
                    break;
                case 0xDD:
                    r = 0xdd;
                    debug_print("PING");
                    rf_write_buf(&r, 1);
                    break;
				case 0xFF:
					set_code();
					break;
                //default:
                //    pc.printf("Unknown command %x", cmd);
            }
        }
    }
}
