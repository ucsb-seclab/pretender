# Pretender
Pretender uses Avatar to record memory-mapped input/output (MMIO) 
interactions on embedded systems and then create high-fidelity models of 
those interactions to be used in QEMU.

This directory is laid out as follows:
 - *pretender*: Pretender python module
 - *scripts*: Supplementary scripts for running tests etc.
 - *firmware*: Symbolic links to firmware samples used in our testing.
 - *bin*: Core binaries for Pretender use for recording, training, and replaying
 
# Installation

Pretender can be installed like other Python packages, e.g. via
```bash
sudo python setup.py install
```
or
```bash
pip install -e .
```

# Example Usage

## Record an execution
This will run the firmware 3 times, waiting for a default 120 s each time, 
and recording all of the MMIO accesses for each run in a separate 
tab-separated value file.
```bash
pretender-recorder -s firmware/Nucleo_blink_led.bin -r 3 -o led_3_runs
```

Once we have the recording, we can build a model from that recording, that 
will be saved to a *.model* file to be shared and exported.
```bash
pretender-train-model -r led_3_runs
```

We can now use the model to emulate the firmware entirely in QEMU,
```bash
pretender-emulate -s firmware/Nucleo_blink_led.bin -r led_3_runs/
```
or we can run the model alongside a real execution to see how well our model 
performs.
```bash
pretender-comparison -s firmware/Nucleo_blink_led.bin -r led_3_runs
```
In this case, all of the comparison results will be saved in the recording 
directory in the file *comparison_results.tsv*

Note that the timings in these emulated versions are almost dead on to the 
original timing in the source, using our linear regression model.

```C
#include "mbed.h"

DigitalOut myled(LED1);

int main() {
    while(1) {
        myled = 1; // LED is ON
        wait(0.2); // 200 ms
        myled = 0; // LED is OFF
        wait(1.0); // 1 sec
    }
}
```
