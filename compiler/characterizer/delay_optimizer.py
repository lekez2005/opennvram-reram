from typing import List

import numpy as np
from scipy.optimize import Bounds, minimize

import debug
from characterizer.delay_loads import DistributedLoad, InverterLoad, ParasiticLoad, WireLoad, PrechargeLoad, NandLoad, \
    ParasiticNandLoad


class LoadOptimizer:

    @staticmethod
    def generate_en_delay(num_stages, loads: List[DistributedLoad],
                          driver_c_drain=1, final_stage=True):
        """
        Generate delay function for optimization
        :param num_stages: number of stages subsequent to the initial size 1 inverter/nand/nor driver
        :param loads: actual loads to be driven e.g. [sense_amp_array]
        :param driver_c_drain: The preceding driver's drain capacitance relative to inverter.
                1 if driver is an inverter, 2 if driver is a nand or nor
        :param final_stage Whether this is the final stage or needs to drive the final stage alongside the real load
        :return: (initial_guess, delay_func, all_delays)
        """

        # assumes an initial stage with drive strength 1
        delay_stages = num_stages if final_stage else num_stages - 1

        def all_stage_delays(x):
            stage_delays = [0]*(delay_stages + 1)

            # first stage
            driver = ParasiticLoad(1)
            stage_delays[0] = driver_c_drain*driver.delay() + InverterLoad(x[0], driver).delay()
            # intermediate stages
            for i in range(1, delay_stages):
                driver_size = x[i-1]
                load_size = x[i]
                driver = ParasiticLoad(driver_size)
                stage_delays[i] = driver.delay() + InverterLoad(load_size, driver).delay()

            # final stage
            driver = ParasiticLoad(x[delay_stages-1])
            final_delay = 0

            if not final_stage:
                final_delay += InverterLoad(x[delay_stages], driver).delay()

            for load_ in loads:
                load_.driver.driver = driver
                final_delay += load_.driver.delay() + load_.delay()
            stage_delays[-1] = final_delay

            return stage_delays

        def optimization_func(x):
            return 1e12*sum(all_stage_delays(x))  # scale to prevent machine precision errors

        def total_delay(x):
            return sum(all_stage_delays(x))

        # find initial guess
        total_load = 0
        for load in loads:
            total_load += load.total_cap
        relative_load = total_load/ParasiticLoad(1).delay_params.c_gate
        scale_factor = relative_load**(1/(num_stages+1))
        initial_guess = np.asarray([scale_factor**x for x in range(1, num_stages+1)])

        return initial_guess, optimization_func, total_delay, all_stage_delays

    @staticmethod
    def generate_en_en_bar_delay(num_stages, final_loads: List[DistributedLoad],
                                 penultimate_loads: List[DistributedLoad], driver_c_drain=1):
        """
        Generate delay objective functions for both en and en_bar loads in a buffer chain
        :param num_stages:
        :param final_loads:
        :param penultimate_loads:
        :param driver_c_drain:
        :return:
        """
        _, pen_opt_func, _, all_pen_delays = LoadOptimizer.\
            generate_en_delay(num_stages, penultimate_loads, driver_c_drain, final_stage=False)
        initial_guess, fin_opt_func, final_delay, all_final_delays = LoadOptimizer.\
            generate_en_delay(num_stages, final_loads, driver_c_drain, final_stage=True)

        def optimization_func(x, penalty=100):
            """Penalize non-equal delays"""
            pen_delay = pen_opt_func(x)
            fin_delay = fin_opt_func(x)
            return pen_delay + fin_delay + penalty*(fin_delay - pen_delay)**2

        def total_delay(x):
            return sum(all_stage_delays(x)[:-1])

        def all_stage_delays(x):
            pen_delays = all_pen_delays(x)
            fin_delays = all_final_delays(x)

            fin_delays[-1] = fin_delays[-2] + fin_delays[-1]
            fin_delays[-2] = pen_delays[-1]

            return fin_delays

        return initial_guess, optimization_func, total_delay, all_stage_delays

    @staticmethod
    def generate_precharge_delay(num_stages: int, num_cols: int, wire_driver: WireLoad,
                                 bitline_load: DistributedLoad, driver_c_drain=1):

        def all_stage_delays(x):
            stage_delays = [0] * (num_stages + 2)

            # first stage
            driver = ParasiticLoad(1)
            stage_delays[0] = driver_c_drain * driver.delay() + InverterLoad(x[0], driver).delay()

            # intermediate stages
            for i in range(1, num_stages):
                driver_size = x[i - 1]
                load_size = x[i]
                driver = ParasiticLoad(driver_size)
                stage_delays[i] = driver.delay() + InverterLoad(load_size, driver).delay()

            precharge_size = x[-1]

            # buffer stage to precharge array
            final_buffer_driver = ParasiticLoad(x[num_stages - 1])
            wire_driver.driver = final_buffer_driver
            precharge_array = PrechargeLoad(precharge_size, wire_driver, num_cols)

            stage_delays[-2] = wire_driver.delay() + precharge_array.delay()

            # precharge array to bitline
            # assume 3x * size inverter driver for bitline
            single_precharge = ParasiticLoad(precharge_size)
            bitline_load.driver = single_precharge

            stage_delays[-1] = single_precharge.delay() + bitline_load.delay()

            return stage_delays

        def optimization_func(x):
            return 1e12*sum(all_stage_delays(x))  # scale to prevent machine precision errors

        def total_delay(x):
            return sum(all_stage_delays(x))

        initial_guess = list(range(1, num_stages+2))

        return initial_guess, optimization_func, total_delay, all_stage_delays

    @staticmethod
    def generate_decoder_delay(num_stages: int, row_decoder_load: DistributedLoad):

        def all_stage_delays(x):
            stage_delays = [0] * (num_stages + 2)
            # first stage
            driver = ParasiticLoad(1)
            nand_load = NandLoad(x[0], driver)
            stage_delays[0] = driver.delay() + nand_load.delay()

            # NAND to inverter
            nand_driver = ParasiticNandLoad(x[0])
            inverter_load = InverterLoad(x[1], nand_driver)
            stage_delays[1] = nand_driver.delay() + inverter_load.delay()

            for i in range(2, num_stages+1):
                driver_size = x[i]
                load_size = x[i+1]
                driver = ParasiticLoad(driver_size)
                stage_delays[i] = driver.delay() + InverterLoad(load_size, driver).delay()

            # last inverter to row decoder
            driver = ParasiticLoad(x[-1])
            row_decoder_load.driver = driver
            stage_delays[-1] = driver.delay() + row_decoder_load.delay()

            return stage_delays

        def optimization_func(x):
            return 1e12*sum(all_stage_delays(x))

        def total_delay(x):
            return sum(all_stage_delays(x))

        initial_guess = list(range(1, num_stages+2))
        return initial_guess, optimization_func, total_delay, all_stage_delays

    @staticmethod
    def relax_equalization(opt_func):
        """
        Remove constraint of the en and en_bar being equal.
        Should only be called for functions returned by generate_en_en_bar_delay
        :param opt_func: the function to be wrapped
        :return:
        """
        def wrapped(*args, **kwargs):
            if 'penalty' not in kwargs:
                kwargs['penalty'] = 0
            return opt_func(*args, **kwargs)
        return wrapped

    @staticmethod
    def minimize_delays(opt_func, initial_guess, max_size: float, method='SLSQP', bounds=None):
        """
        Minimize delay given a maximum buffer size
        :param opt_func: Objective function
        :param initial_guess:
        :param max_size: max inverter size
        :param method: scipy optimization method e.g. SLSQP, COBYLA
        :param bounds: bounds for each delay stage
        :return: numpy array of buffer sizes
        """
        initial_guess = np.asarray(initial_guess)
        num_variables = len(initial_guess)

        if not bounds:
            bounds = Bounds(np.ones(num_variables), max_size * np.ones(num_variables), keep_feasible=True)
        stages = minimize(opt_func, initial_guess, method=method, bounds=bounds)

        return stages

    @staticmethod
    def minimize_sizes(opt_func, initial_guess, max_delay, all_stage_delays, final_stage=False,
                       equalize_final_stages=False, method='SLSQP'):
        """
        Minimize sizes given a maximum delay
        :param opt_func: Objective function
        :param initial_guess:
        :param max_delay: max delay
        :param all_stage_delays: function returning delay of each stage
        :param final_stage: if true, just keep the final stage delay below max_delay
         else keep both en and en_bar delays below max_delay
        :param equalize_final_stages: whether delay of en and en_bar should be equal, ignored when final_stage=True
        :param method: scipy optimization method e.g. SLSQP, COBYLA
        :return: numpy array of buffer sizes
        """

        initial_guess = np.asarray(initial_guess)
        num_variables = len(initial_guess)

        def make_constraint(func):

            def wrapped_func(x):
                return max_delay - func(x)

            return {'type': 'ineq', 'fun': wrapped_func}

        def penultimate_func(x):
            delays = all_stage_delays(x)
            return sum(delays[:-1])

        if final_stage:
            def final_delay_func(x):
                delays = all_stage_delays(x)
                return sum(delays)

            constraints = [make_constraint(final_delay_func)]
        else:
            def final_delay_func(x):
                delays = all_stage_delays(x)
                return sum(delays) - delays[-2]
            constraints = [make_constraint(penultimate_func), make_constraint(final_delay_func)]

        if not final_stage and not equalize_final_stages:
            opt_func = LoadOptimizer.relax_equalization(opt_func)

        # first optimize to find a feasible delay
        result = LoadOptimizer.minimize_delays(opt_func, initial_guess, np.inf)
        initial_guess = result.x

        if penultimate_func(initial_guess) > max_delay or final_delay_func(initial_guess) > max_delay:
            debug.error("max_delay {} cannot be satisfied for any buffer size combination".format(max_delay),
                        debug.ERROR_CODE)

        bounds = Bounds(np.ones(num_variables), np.inf * np.ones(num_variables), keep_feasible=True)
        stages = minimize(sum, initial_guess, method=method, constraints=constraints, bounds=bounds)
        return stages
