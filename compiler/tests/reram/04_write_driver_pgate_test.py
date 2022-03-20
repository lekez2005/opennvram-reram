from reram_test_base import ReRamTestBase


class WriteDriverPgateTest(ReRamTestBase):

    # def test_write_driver_mux_logic(self):
    #     from modules.write_driver_mux_logic import WriteDriverMuxLogic
    #     cell = WriteDriverMuxLogic(size=None)
    #     self.local_check(cell)

    def test_write_driver_mux_buffer(self):
        from modules.write_driver_mux_separate_vdd import WriteDriverMuxSeparateVdd
        cell = WriteDriverMuxSeparateVdd()
        self.local_check(cell)
    #
    # def test_write_driver_pgate(self):
    #     from modules.reram.write_driver_pgate import WriteDriverPgate
    #     cell = WriteDriverPgate(logic_size=1, buffer_size=1)
    #     self.local_check(cell)
    #
    # def test_large_write_driver_page(self):
    #     from modules.reram.write_driver_pgate import WriteDriverPgate
    #     cell = WriteDriverPgate(logic_size=1.5, buffer_size=6)
    #     self.local_check(cell)
    #
    # def test_write_driver_separate_vdd(self):
    #     from modules.reram.write_driver_pgate_sep_vdd import WriteDriverPgateSeparateVdd
    #     cell = WriteDriverPgateSeparateVdd(logic_size=1, buffer_size=1)
    #     self.local_check(cell)


WriteDriverPgateTest.run_tests(__name__)
