from config_baseline import *
from sky130_common_config import *
from config_reram_base import *

# module parameters
bitcell_tx_size = 7  # bitcell access device size in um
bitcell_tx_mults = 4  # number of access device fingers
bitcell_width = 2.5  # bitcell width in um

symmetric_bitcell = False
mirror_bitcell_y_axis = True
use_x_body_taps = False
use_y_body_taps = True

bitcell_array = "reram_bitcell_array.ReRamBitcellArray"

separate_vdd_wordline = True
wordline_driver = "reram_wordline_driver_array"
decoder = "reram_row_decoder.reram_row_decoder"

precharge = "bitline_discharge.BitlineDischarge"
precharge_size = 6

ms_flop = "ms_flop_clk_buf.MsFlopClkBuf"
ms_flop_horz_pitch = "ms_flop_horz_pitch.MsFlopHorzPitch"
predecoder_flop = "ms_flop_horz_pitch.MsFlopHorzPitch"
control_flop = "ms_flop_horz_pitch.MsFlopHorzPitch"

sense_amp_array = "sense_amp_array"
sense_amp = "reram_sense_amp.ReRamSenseAmp"

column_mux_array = "single_level_column_mux_array"
column_mux = "tgate_column_mux_pgate"

control_optimizer = "reram_control_buffers_optimizer.ReramControlBuffersOptimizer"

br_reset_buffers = [1, 3.42, 11.7, 40]
bl_reset_buffers = [3.1, 9.65, 30]

logic_buffers_height = 4
run_optimizations = True
control_buffers_num_rows = 2
route_control_signals_left = True
shift_control_flops_down = True

add_buffer_repeaters = False


# simulation params
filament_scale_factor = 1e7
min_filament_thickness = 3.3e-9 * filament_scale_factor
max_filament_thickness = 4.9e-9 * filament_scale_factor
vdd_wordline = 2.5
vdd_write = 2.4
sense_amp_vclamp = 0.9
sense_amp_vclampp = 0.9
sense_amp_vref = 1

state_probe_node = "Xmem.state_out"


def configure_timing(sram, OPTS):
    num_rows = sram.bank.num_rows
    num_cols = sram.bank.num_cols
    wpr = sram.bank.words_per_row

    OPTS.sense_trigger_setup = 0.4  # extra time to continue enable sense amp past read cycle

    first_read = 1.5
    second_read = 3

    trigger_delay = second_read - 0.6
    first_write = 1.5
    second_write = 30

    OPTS.sense_trigger_delay = trigger_delay

    return first_read, first_write, second_read, second_write

# TODO:
# stacked wordline driver
# wordline vdd power
