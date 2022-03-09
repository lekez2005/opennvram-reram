from modules.ms_flop import ms_flop


class ms_flop_horz_pitch(ms_flop):
    """
    Flip flop whose height is close to pgates/bitcell for use in decoders or CAM tags
    """
    lib_name = "ms_flop_horz_pitch"
    pin_names = ["din", "dout", "dout_bar", "clk", "vdd", "gnd"]


