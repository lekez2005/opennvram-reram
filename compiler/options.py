import optparse
import os

class options(optparse.Values):
    """
    Class for holding all of the OpenRAM options. All of these options can be over-riden in a configuration file
    that is the sole required command-line positional argument for openram.py.
    """

    # This is the technology directory.
    openram_tech = ""
    # This is the name of the technology.
    tech_name = ""
    # This is the temp directory where all intermediate results are stored.
    openram_temp = None

    # This is the verbosity level to control debug information. 0 is none, 1
    # is minimal, etc.
    debug_level = 0
    # This determines whether  LVS and DRC is checked for each submodule.
    check_lvsdrc = True
    # Variable to select the variant of spice
    spice_name = ""
    # Should we print out the banner at startup
    print_banner = True
    # The DRC/LVS/PEX executable being used which is derived from the user PATH.
    drc_exe = None
    lvs_exe = None
    pex_exe = None

    simulator_threads = 24

    use_ultrasim = False
    ultrasim_speed = 3  # 1 (most accurate) -> 8 (least accurate)
    ultrasim_mode = "s"  # a for analog, s for spice. spice is more accurate

    # The spice executable being used which is derived from the user PATH.
    spice_exe = ""
    # Run with extracted parasitics
    use_pex = False
    # Remove noncritical memory cells for characterization speed-up
    trim_netlist = False
    # Use detailed LEF blockages
    detailed_blockages = True
    # Define the output file paths
    output_path = "."
    # Define the output file base name
    output_name = ""
    # Use analytical delay models by default rather than (slow) characterization
    analytical_delay = True
    # Purge the temp directory after a successful run (doesn't purge on errors, anyhow)
    purge_temp = False

    # These are the configuration parameters
    rw_ports = 1
    r_ports = 0
    # These will get initialized by the the file
    supply_voltages = ""
    temperatures = ""
    process_corners = ""

    spectre_format = "psfbin"
    spectre_ic_mode = "node"
    spectre_simulator_options = " "
    decoder_flops = False

    verbose_save = False  # whether to save all lots of internal nodes e.g. cols for control signals, currents

    separate_vdd = False
    separate_vdd_wordline = False

    # cache delay optimization buffer sizes and suffix
    cache_optimization = True
    cache_optimization_prefix = ""

    # use data from characterizations or dynamically compute
    use_characterization_data = True
    # Require exact match in loading characterization data or permit interpolation
    interpolate_characterization_data = True

    # for delay graph evaluation, if number of driven loads is greater than N,
    # the load is considered distributed if the load is also on the main path i.e. not is_branch
    distributed_load_threshold = 8

    # These are the default modules that can be over-riden
    decoder = "hierarchical_decoder"
    col_decoder = "column_decoder"
    ms_flop = "ms_flop"
    ms_flop_mod = "ms_flop"
    ms_flop_tap_mod = "ms_flop_tap"
    mask_in_flop = ms_flop
    mask_in_flop_tap = "ms_flop_tap"

    predecoder_flop = "ms_flop_horz_pitch"
    predecoder_flop_layout = "h"  # v for side by side, h for one above the other

    ms_flop_array = "ms_flop_array"
    ms_flop_array_horizontal = "ms_flop_array_horizontal"
    ms_flop_horz_pitch = "ms_flop_horz_pitch"
    dff = "dff"
    dff_array = "dff_array"
    control_logic = "control_logic"
    bitcell_array = "bitcell_array"
    sense_amp = "sense_amp"
    sense_amp_mod = "sense_amp"
    sense_amp_tap = "sense_amp_tap"
    sense_amp_array = "sense_amp_array"
    precharge_array = "precharge_array"
    column_mux = "single_level_column_mux"
    column_mux_array = "single_level_column_mux_array"
    write_driver = "write_driver"
    write_driver_mod = "write_driver"
    write_driver_array = "write_driver_array"
    tri_gate_mod = "tri_gate"
    tri_gate = "tri_gate"
    tri_gate_array = "tri_gate_array"
    wordline_driver = "wordline_driver"
    replica_bitline = "replica_bitline"
    replica_bitcell = "replica_bitcell"
    bitcell = "bitcell"
    bitcell_mod = "cell_6t"
    delay_chain = "delay_chain"
    body_tap = "body_tap"
    control_flop = "ms_flop_horz_pitch"
    flop_buffer = "flop_buffer.FlopBuffer"

    # buffer stages
    max_buf_size = 40
    # Penalize large buffer sizes. Add 'penalty'*(sum(sizes)) ps to delays
    buffer_optimization_size_penalty = 0.05
    control_logic_clk_buffer_stages = [2, 6, 16, 24]  # buffer stages for control logic clk_bar and clk_buf
    control_logic_logic_buffer_stages = [2.5, 8]  # buffer stages for control logic outputs except clks
    bank_gate_buffers = {  # buffers for bank gate. "default" used for unspecified signals
        "default": [2, 4, 8],
        "clk": [2, 6, 12, 24, 24]
    }
    # For num_banks == 2, whether to spread word across the two banks or make them independent
    independent_banks = True
    # Create separate buffered clock for decoders or use clk_buf (shared with flops)
    create_decoder_clk = True
    decoder_clk_stages = [4]
    bank_sel_stages = [4]

    control_buffers_num_rows = 2
    # Whether external precharge trigger signal is supplied.
    # If no precharge_trigger, precharge uses the clock edges
    use_precharge_trigger = False

    precharge_size = 4
    max_precharge_size = 10
    max_column_decoder_buffers = 8
    column_mux_size = 8

    # bitcell config
    # bitcell can be mirrored across y axis without really swapping bitlines
    symmetric_bitcell = True
    mirror_bitcell_y_axis = False
    cells_per_group = 1
    num_bitcell_dummies = 0
    dummy_cell = None
    export_dummy_bitcell_pins = True

    use_x_body_taps = True  # bitcell does not include body taps so insert body taps between bitcells columns
    use_y_body_taps = False # insert taps between bitcell rows

    # control signals routing configuration
    # whether to route rails to the left of the peripherals array
    route_control_signals_left = False
    # whether to connect to array closest to the buffer or closer to the middle of the array
    # applies when not 'route_control_signals_left'
    centralize_control_signals = False

    # whether control flops within bank should be shifted down when row decoder overlaps
    # if false, the row decoder will be shifted left at the top level sram
    shift_control_flops_down = True

    # repeaters configuration
    add_buffer_repeaters = True  # whether to add repeaters
    # whether to add dedicated space between bitcells or just use space between the bitlines
    dedicated_repeater_space = False
    # repeater x offset relative to total array width
    repeater_x_offset = 0.7
    # repeaters will be added if num_cols in a bank > this
    buffer_repeaters_col_threshold = 128
    # repeater sizes e.g. ("clk_bar", ["clk_buf", "clk_bar"], [10, 15, 20])
    # takes "clk_bar" output from control buffer, adds inverter chain 10-20
    # output of 15 goes to clk_bar, output of 20 goes to clk_buf
    buffer_repeater_sizes = []

    predecode_sizes = [1, 2]
    control_flop_buffers = [2]  # buffer for control flop

    sense_amp_type = "sense_amp"
    LATCHED_SENSE_AMP = "latched_sense_amp"
    MIRROR_SENSE_AMP = "sense_amp"

    # for number of bitcells between M4 bitcell grids
    bitcell_vdd_spacing = 10

    def __init__(self):
        super().__init__()
        self.set_temp_folder()

    def set_temp_folder(self, openram_temp=None):
        # openram_temp is the temp directory where all intermediate results are stored.
        openram_temp = openram_temp or self.openram_temp
        default_openram_temp = os.path.join(os.environ.get("SCRATCH", "/tmp"), "openram")
        if openram_temp is None:
            openram_temp = default_openram_temp
        elif not os.path.isabs(openram_temp):
            openram_temp = os.path.join(default_openram_temp, openram_temp)

        self.openram_temp = openram_temp
        self.log_file = os.path.join(openram_temp, 'openram.log')

        self.spice_file = os.path.join(openram_temp, 'temp.sp')
        self.pex_spice = os.path.join(openram_temp, 'pex.sp')
        self.reduced_spice = os.path.join(openram_temp, 'reduced.sp')
        self.gds_file = os.path.join(openram_temp, 'temp.gds')
        self.ic_file = os.path.join(openram_temp, "sram.ic")

