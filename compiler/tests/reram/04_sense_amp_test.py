from reram_test_base import ReRamTestBase


class SenseAmpTest(ReRamTestBase):
    def test_sense_amp(self):
        cell = self.create_class_from_opts("sense_amp")
        self.local_check(cell)


SenseAmpTest.run_tests(__name__)
