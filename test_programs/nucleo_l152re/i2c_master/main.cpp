#include "mbed.h"
 
#define AM2315_I2CADDR       0x5C
#define AM2315_READREG       0x03

I2C i2c(I2C_SDA, I2C_SCL);
 
DigitalOut myled(LED1);
 
Serial pc(SERIAL_TX, SERIAL_RX);


void die() {
	while (1) {
    	myled = !myled;
        wait(0.2);
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

float get_humidity(uint8_t* reply) {
	float humidity;
	humidity = reply[2];
	humidity *= 256;
	humidity += reply[3];
	humidity /= 10;
	return humidity;
}

float get_temp(uint8_t* reply) {
	float temp;
	temp = reply[4] & 0x7F;
	temp *= 256;
	temp += reply[5];
	temp /= 10;
	return temp;
}

int main()
{
    wait(5.0);
    uint8_t data_read[10];
    while (1) {
       
        // Calculate temperature value in Celcius
		read_data(data_read);
		float temp = get_temp(data_read);
		float humidity = get_humidity(data_read);
 
        // Display result
        pc.printf("temp = %2f\n", temp);
        pc.printf("humidity = %2f\n", humidity);
        wait(1.0);
    }
 
}
 
