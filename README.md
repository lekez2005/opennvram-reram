OpenRAM Port to support Reram array generation

Please refer to the [parent OpenRAM project](https://github.com/VLSIDA/OpenRAM) for full instructions on running OpenRAM. This project contains only files necessary for generating and simulating ReRAM arrays in Sky130nm process.

For sky130, klayout and magic and netgen are required for DRC/LVS runs.

`compiler/tests/reram/caravel/caravel_reram_test.py` is the entry point for generating the caravel-wrapped SRAM array. Example run command:

   ```$ caravel_reram_test.py -t sky130 -v```

The generated SRAM arrays are combined into a single SRAM array to enable independent testing of each array. The combined SRAM array is then wrapped into Caravel configurations are specified in [caravel_user_project_analog](https://github.com/efabless/caravel_user_project_analog)'s padframe.

Caravel-level configurations are specified in `compiler/tests/reram/caravel/caravel_config.py`. In `caravel_config.py`, you can configure the size of each of the four SRAM banks, the esd diodes sizes, and some simulation configurations.

