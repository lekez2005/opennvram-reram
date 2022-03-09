from reram_test_base import ReRamTestBase


class HorizotalFlopTest(ReRamTestBase):
    def test_horizontal_flop(self):
        from ms_flop_horz_pitch import MsFlopHorzPitch
        cell = MsFlopHorzPitch()
        self.local_check(cell)


HorizotalFlopTest.run_tests(__name__)
