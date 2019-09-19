#!/usr/bin/env bash
SAMPLE="../test_programs/nucleo_l1/i2c_master/BUILD/Nucleo_i2c_master.bin"
CFG="../python-pretender/configs/nucleo_l1.yaml"
OUT="./i2c_l152"
BOARD=1

echo "Recording..."
../python-pretender/bin/pretender-recorder -I -b $BOARD --board-config $CFG -C  -s $SAMPLE -r 3 -o $OUT
echo "Building a model"
../python-pretender/bin/pretender-model-generate -r $OUT
echo "Comparing the models"
../python-pretender/bin/pretender-emulate  -I -t 300 --board-config $CFG -C -s $SAMPLE -r $OUT
