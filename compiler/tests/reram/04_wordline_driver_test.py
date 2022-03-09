from reram_test_base import ReRamTestBase


class WordlineDriverTest(ReRamTestBase):
    def test_wordline_driver(self):
        from globals import OPTS
        cell = self.create_class_from_opts("wordline_driver", rows=64,
                                           buffer_stages=OPTS.wordline_buffers)
        self.local_check(cell)


WordlineDriverTest.run_tests(__name__)
