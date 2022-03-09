from config_baseline import *
from config_baseline import configure_modules as default_configure_modules
from freepdk45_common_config import *

setup_time = 0.05  # in nanoseconds
precharge_size = 5
max_precharge_size = 6.5
max_precharge_buffers = 60

write_driver_mod = "write_driver_mux_buffer"
write_buffers = [1, 3.42, 11.7, 40]

use_precharge_trigger = False


def configure_modules(bank, OPTS):
    default_configure_modules(bank, OPTS)
    if bank.words_per_row > 1:
        OPTS.write_driver_mod = "write_driver_mux_buffer"
    else:
        OPTS.write_driver_mod = "write_driver_mask"


def configure_timing(sram, OPTS):
    num_rows = sram.bank.num_rows
    num_cols = sram.bank.num_cols
    OPTS.sense_trigger_setup = 0.15
    OPTS.precharge_trigger_delay = 0.6
    if num_rows == 16 and num_cols == 64:
        first_read = 0.3
        second_read = 0.4
        OPTS.sense_trigger_delay = second_read - 0.2
        first_write = 0.3
        second_write = 0.3
    elif num_rows == 64 and num_cols == 64:
        first_read = 0.4
        second_read = 0.45
        OPTS.sense_trigger_delay = second_read - 0.2
        first_write = 0.4
        second_write = 0.45
    elif num_rows == 128 and num_cols == 128:
        first_read = 0.6
        second_read = 0.65
        OPTS.sense_trigger_delay = second_read - 0.2
        first_write = 0.6
        second_write = 0.7
    elif num_rows == 256 and num_cols == 128:
        first_read = 0.9
        second_read = 0.75
        OPTS.sense_trigger_delay = second_read - 0.2
        first_write = 0.9
        second_write = 1.15
    elif num_rows == 64 and num_cols == 128:  # upstream comparison
        first_read = 0.5
        second_read = 0.5
        OPTS.sense_trigger_delay = second_read - 0.2
        first_write = 0.4
        second_write = 0.55
    else:
        if OPTS.num_banks == 1:
            OPTS.precharge_trigger_delay = 1
            first_read = first_write = 0.9
            second_read = 0.8
            OPTS.sense_trigger_delay = second_read - 0.25
            second_write = 1.5
        else:
            OPTS.sense_trigger_delay = 0.5
            first_read = first_write = 0.75
            OPTS.precharge_trigger_delay = first_read + 0.1
            second_read = OPTS.sense_trigger_delay + 0.2
            second_write = 0.7

    return first_read, first_write, second_read, second_write
