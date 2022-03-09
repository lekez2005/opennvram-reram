import os

# modules
decoder_flops = True
separate_vdd = False

write_driver_mod = "write_driver_mask_3x"
write_driver_tap = "write_driver_tap"
write_driver_tap_mod = "write_driver_mask_3x_tap"
write_driver_array = "write_driver_mask_array"
wordline_driver = "wordline_driver_array"

mask_in_flop = "ms_flop_clk_buf"
mask_in_flop_tap = "ms_flop_clk_buf_tap"

data_in_flop = "ms_flop_clk_buf"
data_in_flop_tap = "ms_flop_clk_buf_tap"

# data_in_flop = "ms_flop"
# data_in_flop_tap = "ms_flop_tap"
control_flop = "ms_flop_horz_pitch"
column_mux_array = "tgate_column_mux_array"
sense_amp_mod = "latched_sense_amp"
sense_amp_tap = "latched_sense_amp_tap"
sense_amp_array = "latched_sense_amp_array"
sense_amp_type = "latched_sense_amp"
control_buffers_class = "baseline_latched_control_buffers.LatchedControlBuffers"
bank_class = "baseline_bank.BaselineBank"
sram_class = "baseline_sram.BaselineSram"

run_optimizations = True

# Buffer configurations
logic_buffers_height = 1.4

max_buf_size = 40
max_clk_buffers = max_buf_size
max_wordline_en_buffers = max_buf_size
max_write_buffers = max_buf_size
max_sense_en_size = max_buf_size
max_precharge_en_size = max_buf_size
max_wordline_buffers = 20
max_predecoder_inv_size = 20
max_predecoder_nand = 1.2

wordline_buffers = [1, 5, 20]
predecode_sizes = [1.2, 4]
write_buffers = [1, 5, 25, 50, 65]
wordline_en_buffers = [1, 3.7, 13.6, 50]
clk_buffers = [1, 5, 20, 65, 30]  # clk only used by decoders (no latches)
sampleb_buffers = [1, 3.7, 13.6, 50]
control_flop_buffers = [4]
sense_amp_buffers = [3.56, 12.6, 45]
tri_en_buffers = [3.42, 11.7, 40, 40]
precharge_buffers = [1, 3.9, 15, 60]
precharge_size = 1.5
column_decoder_buffers = [2, 2]

# default sizes config
word_size = 64
num_words = 64
num_banks = 1
words_per_row = 1

# simulation
slew_rate = 0.005  # in nanoseconds
c_load = 1  # femto-farads
setup_time = 0.015  # in nanoseconds
feasible_period = 1.8  # in nanoseconds
duty_cycle = 0.35

sense_trigger_delay = 0.5

# Buffer repeaters config
# schematic simulation's positive feedback loop may be hard to break
buffer_repeater_sizes = [
    ("clk_bar", ["clk_buf", "clk_bar"], [20, 20]),
    ("sense_en", ["sense_en"], [5, 15]),
    ("write_en", ["write_en_bar", "write_en"], [20, 20]),
    # ("sample_en_bar", ["sample_en_bar"], [5, 15]),
    ("tri_en", ["tri_en_bar", "tri_en"], [10, 10]),
    ("precharge_en_bar", ["precharge_en_bar"], [10, 20]),
]
buffer_repeaters_col_threshold = 128


def configure_modules(bank, OPTS):
    # TODO multi stage buffer for predecoder col mux. pnor3 too large for 3x8 buffer
    if bank.words_per_row > 2:
        OPTS.column_decoder_buffers = [4]  # use single stage
    num_rows = bank.num_rows
    num_cols = bank.num_cols
    if num_rows > 127:
        OPTS.max_wordline_en_buffers = 60
    else:
        OPTS.max_wordline_en_buffers = 30

    if num_cols < 100:
        OPTS.num_clk_buf_stages = 4
        OPTS.num_write_en_stages = 4
        OPTS.max_clk_buffers = 40
        OPTS.max_write_buffers = 40
        # OPTS.tri_en_buffers = [, 11.7, 40, 40]
    else:
        OPTS.num_clk_buf_stages = 5
        OPTS.num_write_en_stages = 5
        OPTS.max_clk_buffers = 60
        OPTS.max_write_buffers = 60
        OPTS.tri_en_buffers = [3.42, 11.7, 40, 40]
