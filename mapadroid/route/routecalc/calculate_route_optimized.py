import math
import multiprocessing
import secrets

from mapadroid.utils.logging import logger
from .util import *


def route_calc_impl(lessCoordinates, route_name, num_processes):
    init_temp = 100
    halt = 120
    markov_coefficient = 10

    # Constant Definitions
    NUM_NEW_SOLUTION_METHODS = 3
    SWAP, REVERSE, TRANSPOSE = 0, 1, 2
    coordinates = lessCoordinates.copy()
    # Params Initial
    num_location = coordinates.shape[0]
    markov_step = markov_coefficient * num_location
    T_0, T, T_MIN = init_temp, init_temp, 1
    T_NUM_CYCLE = 1
    # Build distance matrix to accelerate cost computing
    distmat = get_distmat(coordinates)
    # States: New, Current and Best
    sol_new, sol_current, sol_best = (np.arange(num_location),) * 3
    cost_new, cost_current, cost_best = (float('inf'),) * 3
    # Record costs during the process
    costs = []
    # previous cost_best
    prev_cost_best = cost_best
    # counter for detecting how stable the cost_best currently is
    cost_best_counter = 0
    # num_cores = multiprocessing.cpu_count()
    if num_processes != 1:
        from multiprocessing import Pool

        if num_processes > 1:
            num_cores = 1
        else:
            num_cores = multiprocessing.cpu_count()

        thread_pool = Pool(processes=num_cores)
    else:
        num_cores = 1
        thread_pool = None
    # Simulated Annealing
    output_percs = []
    if markov_step > 500:
        output_levels = 0.01
    elif markov_step > 250:
        output_levels = 0.025
    elif markov_step > 100:
        output_levels = 0.05
    else:
        output_levels = 0.1
    logger.info("There are {} markov steps.  Updating status every {}%", markov_step,
                round(output_levels * 100, 1))
    while T > T_MIN and cost_best_counter < halt:
        logger.debug("Still calculating... cost_best_counter: {}",
                     str(cost_best_counter))
        perc_comp = float(cost_best_counter / halt)
        try:
            last_comp = output_percs[-1]
        except:
            last_comp = 0
        rounded_perc = round(output_levels * float(math.floor(float(perc_comp) / output_levels)), 2)
        if rounded_perc > last_comp:
            output_percs.append(rounded_perc)
            logger.info("Route calculation is {}% complete for {}", round(rounded_perc * 100, 1), route_name)
        if num_cores and num_cores != 1 and thread_pool and cost_best_counter > 0:
            running_calculations = []
            full = secrets.randbelow(2)

            for i in range(num_cores):
                # method = np.random.randint(NUM_NEW_SOLUTION_METHODS)
                method = secrets.randbelow(NUM_NEW_SOLUTION_METHODS)
                if full == 0:
                    calculation = thread_pool.apply_async(__generate_new_solution, args=(
                        method, int(round(markov_step / (num_cores * 2 / 3))), distmat, T,
                        cost_best, sol_best))
                elif cost_best_counter > halt * 0.3:
                    calculation = thread_pool.apply_async(__generate_new_solution,
                                                          args=(-1, markov_step, distmat, T,
                                                                cost_best, sol_best))
                else:
                    calculation = thread_pool.apply_async(__generate_new_solution,
                                                          args=(
                                                              -1,
                                                              int(round(markov_step / round(num_cores / 2))),
                                                              distmat,
                                                              T,
                                                              cost_best, sol_best))
                running_calculations.append(calculation)

            # thread_pool.close()
            # thread_pool.join()
            solutions_temp = []
            costs_temps = []
            for i in range(len(running_calculations)):
                # TODO: check this iteration, apparently only gets the first...
                cost_temp, solution_temp = running_calculations[i].get()

                if cost_temp < cost_best:
                    logger.debug("Subprocess found better solution")
                    # cost_best = cost_temp
                    # sol_best = solution_temp.copy()
                    costs_temps.append(cost_temp)
                    solutions_temp.append(solution_temp.copy())
                else:
                    # logger.info("Subprocess did not find a better solution")
                    cost_best_counter += 1
            # if costs_temps.count(costs_temps[0]) == len(costs_temps):
            #     cost_best_counter += 1

            # now check the better solutions if we can merge them ;)
            if len(costs_temps) == 0:
                logger.debug("No better solution...")
            elif len(costs_temps) == 1:
                cost_best = costs_temps[0]
                sol_best = solutions_temp[0].copy()
            else:
                # multiple solutions, so much fun at once!
                merged_sol = sol_best.copy()
                length_sols_minus_one = len(solutions_temp) - 1
                # logger.error("Length solutions minus one: {}", str(length_sols_minus_one))
                # range_to_be_searched = range(length_sols_minus_one)
                # logger.error("Scanning range: {}", str(range_to_be_searched))
                for i in range(len(solutions_temp) - 1):
                    merged_sol = merge_results(
                        merged_sol, solutions_temp[i], solutions_temp[i + 1])
                    # TODO: if merged_sol == sol_best, check for the best solution in the set and use that...
                if np.array_equal(merged_sol, sol_best) or np.array_equal(merged_sol, solutions_temp[0]):
                    for i in range(len(costs_temps)):
                        if costs_temps[i] < cost_best:
                            cost_best = costs_temps[i]
                            sol_best = solutions_temp[i].copy()
                else:
                    sol_best = merged_sol.copy()
                    cost_best = sum_distmat(sol_best, distmat)
        else:
            cost_best, sol_best = __generate_new_solution(
                -1, int(round(num_location * 2)), distmat, T, cost_best, sol_best)

        # Lower the temperature
        alpha = 1 + math.log(1 + T_NUM_CYCLE + 1)
        T = T_0 / alpha
        costs.append(cost_best)

        # Increment T_NUM_CYCLE
        T_NUM_CYCLE += 1

        # Detect stability of cost_best
        if isclose(cost_best, prev_cost_best, abs_tol=1e-12):
            cost_best_counter += 1
        else:
            # Not stable yet, reset
            cost_best_counter = 0

        # Update prev_cost_best
        prev_cost_best = cost_best

        # Monitor the temperature & cost
        # logger.debug("Temperature:", "%.2f°C" % round(T, 2),
        #      " Distance:", "%.2fm" % round(cost_best, 2),
        #      " Optimization Threshold:", "%d" % cost_best_counter)
    if thread_pool is not None:
        thread_pool.close()
        thread_pool.join()
    return sol_best


def __generate_new_solution(method, markov_steps, distmat, temp_current, cost_current, solution_current):
    # Constant Definitions
    NUM_NEW_SOLUTION_METHODS = 3
    SWAP, REVERSE, TRANSPOSE = 0, 1, 2

    sol_best = solution_current.copy()
    sol_current = solution_current.copy()
    cost_best = cost_current
    cost_cur = cost_current
    sol_new = solution_current.copy()
    for i in np.arange(markov_steps):
        if method == -1:
            # choice = np.random.randint(NUM_NEW_SOLUTION_METHODS)
            choice = secrets.randbelow(NUM_NEW_SOLUTION_METHODS)
        else:
            choice = method
        if choice == SWAP:
            sol_new = swap(sol_new)
        elif choice == REVERSE:
            sol_new = reverse(sol_new)
        elif choice == TRANSPOSE:
            sol_new = transpose(sol_new)
        else:
            # logger.debug("ERROR: new solution method %d is not defined" % choice)
            exit(2)
        # Get the total distance of new route
        cost_new = sum_distmat(sol_new, distmat)

        if accept(cost_new, cost_cur, temp_current):
            # Update sol_current
            sol_current = sol_new.copy()
            cost_cur = cost_new
            # TODO: reduce iterator to get more rounds...
            if cost_new < cost_best:
                sol_best = sol_new.copy()
                cost_best = cost_new
        else:
            sol_new = sol_current.copy()

    return cost_best, sol_best.copy()


def get_index_array_numpy_compary(arr_orig, arr_new):
    indices = []
    length_arr = len(arr_orig)
    for i in range(length_arr):  # or range(len(theta))
        if np.array_equal(arr_new[i], arr_orig[i]):
            continue
        else:
            indices.append(i)
    return indices


def merge_results(arr_original, arr_first, arr_second):
    # if we cannot merge it, arr_first will be returned
    differences_first = get_index_array_numpy_compary(arr_original, arr_first)
    differences_second = get_index_array_numpy_compary(
        arr_original, arr_second)

    # check if first index of first is > last index of second and vice-versa
    if len(differences_first) == 0 and len(differences_second) == 0:
        return arr_original
    elif len(differences_second) == 0:
        merged_arr = arr_original.copy()
        for i in differences_first:
            merged_arr[i] = arr_first[i]
        return merged_arr
    elif len(differences_first) == 0:
        merged_arr = arr_original.copy()
        for i in differences_second:
            merged_arr[i] = arr_second[i]
        return merged_arr
    elif differences_first[0] > differences_second[-1]:
        # first index of 'first' is greater than last index of 'second', we can just merge it...
        # TODO
        merged_arr = arr_original.copy()
        for i in differences_first:
            merged_arr[i] = arr_first[i]
        for i in differences_second:
            merged_arr[i] = arr_second[i]
        return merged_arr
    elif differences_second[0] > differences_first[-1]:
        # first index of 'second' is greater than last index of 'first', we can merge without conflicts
        merged_arr = arr_original.copy()
        for i in differences_first:
            merged_arr[i] = arr_first[i]
        for i in differences_second:
            merged_arr[i] = arr_second[i]
        return merged_arr
    else:
        return arr_first
