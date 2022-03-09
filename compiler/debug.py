import inspect
import os
import logging
from logging.handlers import RotatingFileHandler

# the debug levels:
# 0 = minimum output (default)
# 1 = major stages
# 2 = verbose
# n = custom setting

ERROR_CODE = -1

logger = logging.getLogger("debug-logger")
logger.setLevel(logging.DEBUG)  # always log messages

# messages will be pre-formatted
formatter = logging.Formatter("%(message)s")
# add a default console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = None


def wrap_message(prefix, message):
    (frame, filename, line_number, function_name, lines,
     index) = inspect.getouterframes(inspect.currentframe())[2]
    return "{0}: file {1}: line {2}: ".format(prefix, os.path.basename(filename),
                                              line_number) + message


def check(check_, message, *args):
    if check_:
        return
    logger.debug(wrap_message("ERROR", message), *args)
    assert 0, message


def error(message, return_value=-1, *args):
    if return_value == 0:
        return
    logger.debug(wrap_message("ERROR", message), *args)
    assert return_value == 0


def warning(message, *args):
    logger.debug(wrap_message("WARNING", message), *args)


def info(lev, message, *args):
    from globals import OPTS
    if OPTS.debug_level >= lev:
        frm = inspect.stack()[1]
        mod = inspect.getmodule(frm[0])
        # classname = frm.f_globals['__name__']
        if mod.__name__ is None:
            class_name = ""
        else:
            class_name = mod.__name__
        message = "[{0}/{1}]: ".format(class_name, frm[0].f_code.co_name) + message
        logger.debug(message, *args)


def print_str(message):
    logger.debug(message)


class RotateOnOpenHandler(RotatingFileHandler):
    def shouldRollover(self, record):
        if self.stream is None:  # delay was set...
            return 1
        return 0


def setup_file_log(filename):
    global file_handler
    # create directory if it doesn't exist
    directory = os.path.dirname(filename)
    if not os.path.exists(directory):
        os.makedirs(directory)
    if file_handler is not None:
        file_handler.close()
        logger.removeHandler(file_handler)
    file_handler = RotateOnOpenHandler(filename, mode='w', backupCount=5, delay=True)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def pycharm_debug():
    import sys
    if not sys.gettrace():
        import pydevd_pycharm
        pydevd_pycharm.settrace('localhost', port=21000, stdoutToServer=True, stderrToServer=True,
                                suspend=False)
