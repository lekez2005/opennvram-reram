from config_baseline import *
from sky130_common_config import *

bitcell = "reram_bitcell"
bitcell_tx_size = 1  # bitcell access device size in um
bitcell_tx_mults = 4  # number of access device fingers
bitcell_width = 2.5  # bitcell width in um

use_x_body_taps = False
column_mux_array = "single_level_column_mux_array"
column_mux = "tgate_column_mux_pgate"

ms_flop_horz_pitch = "ms_flop_horz_pitch.MsFlopHorzPitch"
control_flop = "ms_flop_horz_pitch.MsFlopHorzPitch"
