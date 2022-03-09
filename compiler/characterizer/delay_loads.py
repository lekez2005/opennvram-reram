from abc import ABC, abstractmethod

from globals import OPTS


class Load(ABC):

    initialized = False
    delay_params = None
    resistance = 0

    @classmethod
    def initialize_class(cls):
        from tech import delay_params_class
        if not cls.initialized:
            cls.delay_params = delay_params_class()()

            c = __import__(OPTS.bitcell)
            cls.mod_bitcell = getattr(c, OPTS.bitcell)
            cls.bitcell = cls.mod_bitcell()

    def __init__(self):
        if not self.initialized:
            self.initialize_class()

    @abstractmethod
    def delay(self):
        pass


class ParasiticLoad(Load):
    """
    Intrinsic delay from c_drain
    """
    drain_cap_rel = 1  # relative to inverter drain cap

    def __init__(self, size):
        super().__init__()

        self.size = size
        self.resistance = self.delay_params.r_intrinsic/size

    def delay(self):
        return self.resistance * self.delay_params.c_drain * self.drain_cap_rel * self.size


class ParasiticNandLoad(ParasiticLoad):
    drain_cap_rel = 2


class CapLoad(Load):
    """Capacitive load"""
    def __init__(self, cap_value, driver: Load):
        super().__init__()
        self.total_cap = cap_value
        self.driver = driver

    def delay(self):
        self.resistance = self.driver.resistance
        return self.resistance * self.total_cap


class InverterLoad(Load):
    def __init__(self, inverter_size, driver: Load):
        """inverter_size is multiple of min sized inverter"""
        super().__init__()
        self.inverter_size = inverter_size
        self.driver = driver

    def delay(self):
        return self.driver.resistance * self.inverter_size * self.delay_params.c_gate


class NandLoad(Load):
    def __init__(self, size, driver: Load):
        """inverter_size is multiple of min sized inverter"""
        super().__init__()
        self.size = size
        self.driver = driver
        self.total_cap = self.size * (self.delay_params.beta + 2)/(
                self.delay_params.beta + 1) * self.delay_params.c_gate

    def delay(self):
        return self.driver.resistance * self.total_cap


class WireLoad(Load):
    def __init__(self, driver: Load, wire_length=0, layer="metal1",
                 wire_width=None, wire_space=None):
        super().__init__()
        if wire_width is None:
            wire_width = self.delay_params.min_width

        c_, r_ = self.delay_params.get_rc(layer, width=wire_width, space=wire_space)

        self.driver = driver
        self.wire_length = wire_length
        self.layer = layer
        self.wire_cap = c_ * wire_length
        self.wire_res = r_ * wire_length / wire_width

    def delay(self):
        self.resistance = self.driver.resistance + self.wire_res
        return self.driver.resistance * self.wire_cap + 0.5 * (self.wire_res * self.wire_cap)


class DistributedLoad(Load):
    def __init__(self, driver: WireLoad, cap_per_stage, stage_width=1, num_stages=16, layer="metal1",
                 wire_width=None):
        super().__init__()

        if wire_width is None:
            wire_width = self.delay_params.min_width

        _, r_ = self.delay_params.get_rc(layer)

        self.driver = driver
        self.wire_res = r_ * stage_width * num_stages / wire_width
        self.total_cap = cap_per_stage * num_stages

    def delay(self):
        self.resistance = self.driver.resistance + self.wire_res
        return self.driver.resistance * self.total_cap + 0.5 * (self.wire_res * self.total_cap)


class PrechargeLoad(DistributedLoad):
    def __init__(self, size, driver: WireLoad, num_cols=64, layer="metal2", wire_width=None):
        super(Load, self).__init__()
        if wire_width is None:
            wire_width = self.delay_params.min_width
        self.driver = driver

        c_, r_ = self.delay_params.get_rc(layer)

        self.wire_res = r_ * self.bitcell.width * num_cols / wire_width

        cap_per_stage = 3*size*self.delay_params.c_gate + c_ * self.bitcell.width
        self.total_cap = cap_per_stage * num_cols
