#!/usr/bin/env bash
SAMPLE="../test_programs/nucleo_f0/blink_led/BUILD/Nucleo_blink_led.bin"
CFG="../python-pretender/configs/nucleo_f0.yaml"
OUT="./f072_led"
BOARD=1

#echo "Recording..."
#../python-pretender/bin/pretender-recorder -b $BOARD --board-config $CFG -C  -s $SAMPLE -r 3 -o $OUT
echo "Building a model"
../python-pretender/bin/pretender-model-generate --old -r $OUT
echo "Comparing the models"
../python-pretender/bin/pretender-emulate --old --board-config $CFG -C -s $SAMPLE -r $OUT
