#include "mbed.h"
 
#define AM2315_I2CADDR       0x5C
#define AM2315_READREG       0x03

I2C i2c(I2C_SDA, I2C_SCL);
 
DigitalOut myled(LED1);
Serial pc(SERIAL_TX, SERIAL_RX);

float target_temp = 22.0;

void die() {
	while (1) {
    	myled = !myled;
        wait(0.2);
    }
} 

int pc_read_buf_vuln(char* buf) {
    int i = 0;
    char c;
    while (1) {
        if (pc.readable()) {
            c = pc.getc();
            buf[i] = c;
            i++;
            if (c == 0) {
                return i;
            }
        }
    }
}

void read_data(uint8_t* data_read) {
	uint8_t data_write[3];
	int addr = AM2315_I2CADDR << 1;
	i2c.write(addr, (char*)data_write, 1, 0);

	data_write[0] = AM2315_READREG;
	data_write[1] = 0x00;  // start at address 0x0
  	data_write[2] = 0x04;  // request 4 bytes data
    int status = i2c.write(addr, (char*)data_write, 3, 0);
    if (status != 0) {
    	pc.printf("Bad write of command");
    	die();
    }
    wait(0.1);
    status = i2c.read(addr, (char*)data_read, 8, 0);
    if (status != 0) {
    	pc.printf("Bad read of command");
    	die();
    }
}

float get_humidity() {
	float humidity;
	uint8_t reply[10];
	read_data(reply);
	humidity = reply[2];
	humidity *= 256;
	humidity += reply[3];
	humidity /= 10;
	return humidity;
}

float get_temp() {
	uint8_t reply[10];
	float temp;
	read_data(reply);
	temp = reply[4] & 0x7F;
	temp *= 256;
	temp += reply[5];
	temp /= 10;
	return temp;
}

float get_new_temp() {
	float new_temp = 0.0;

	char buf[16];
	int i = 0;
	char c;
	while (1) {
		if (pc.readable()) {
			c = pc.getc();
			if (c == 0)
				continue;
			else if (c == 0xd) {
				buf[i] = 0;
				new_temp = atof(buf);
				pc.printf("Temp set to %2f\r\n", new_temp);
				break;
			}
			else {
				buf[i] = c;
				i++;
			}
		}
	}
	return new_temp;
}

void check_temp(float temp) {
	if (temp > target_temp + 0.5) {
		if (!myled) {
			pc.printf("AC ON!\r\n");
			myled = 1;
		}
	}
	else if (temp < target_temp - 0.5) {
		if (!myled) {
			pc.printf("HEATER ON!\r\n");
			myled = 1;
		}
	}
	else {
		if (myled) {
			pc.printf("HEAT/AC OFF\r\n");
			myled = 0;
		}
	}
}

int main()
{
    char cmd;
    pc.printf("Booting firmware...\r\n");
	wait(5.0);
    pc.printf("Booted!\r\n");
    while (1) {
        //pc.printf("Reading sensor...\r\n");
		// Calculate temperature value in Celcius
		float temp;
		float humidity;
        cmd = pc.getc();
		
		switch (cmd) {
            case 't':
                temp = get_temp();
                check_temp(temp);
                pc.printf("%2f\r\n", temp);
                break;
            case 'h':
                humidity = get_humidity();
                pc.printf("%2f\r\n", humidity);
                break;
			case 's':
				target_temp = get_new_temp();
				break;
        }
    }
}

