import argparse
from csv import DictReader
from itertools import izip
from os import path, getcwd, sep

import numpy as np
import spotpy

from scripts.SMARTfiles import get_dict_simulation_settings
from scripts.SMARTobjective import \
    groundwater_constraint, bounded_nash_sutcliffe, sqrt_nash_sutcliffe, spearman_rank_corr, mean_abs_rel_error
from scripts.SMARTpy import SMART


class SpotPySetUp(object):
    def __init__(self, catchment, root_f, save_sim=False):
        in_f = sep.join([root_f, 'in', catchment, sep])

        c_area, g_area, start, end, delta_simu, delta_report, warm_up, gw_constraint = \
            get_dict_simulation_settings(''.join([in_f, catchment, '.sttngs']))

        self.model = SMART(catchment, c_area, g_area, start, end, delta_simu, delta_report, warm_up, root_f)

        self.save_sim = save_sim

        self.constraints = {'gw': gw_constraint}

        self.param_names = ['T', 'C', 'H', 'D', 'S', 'Z', 'SK', 'FK', 'GK', 'RK']
        self.obj_fn_names = \
            ['NSE', 'lgNSE', 'rtNSE', 'C2M', 'KGE', 'KGEc', 'KGEa', 'KGEb', 'Bias', 'PBias', 'RMSE', 'Rho', 'MARE'] \
            if self.constraints['gw'] == -999.0 else \
            ['NSE', 'lgNSE', 'rtNSE', 'C2M', 'KGE', 'KGEc', 'KGEa', 'KGEb', 'Bias', 'PBias', 'RMSE', 'Rho', 'MARE', 'GW']

        # extract behavioural sets from sampling sets
        self.sampling_run_file = ''.join([in_f, catchment, '.SMART.lhs'])
        self.sampled_params, self.sampled_obj_fns = get_sampled_sets_from_file(self.sampling_run_file,
                                                                               self.param_names,
                                                                               self.obj_fn_names)
        self.conditions_values = [(0.75,), (-10, 10), (1.0,)]
        self.conditions_types = ['min', 'inside', 'equal']
        self.behavioural_params = get_behavioural_sets(self.sampled_params, self.sampled_obj_fns[:, [0, 9, 13]],
                                                       self.conditions_values, self.conditions_types)
        # give list of behavioural parameters
        self.params = [
            spotpy.parameter.List(self.param_names[0], self.behavioural_params[:, 0]),
            spotpy.parameter.List(self.param_names[1], self.behavioural_params[:, 1]),
            spotpy.parameter.List(self.param_names[2], self.behavioural_params[:, 2]),
            spotpy.parameter.List(self.param_names[3], self.behavioural_params[:, 3]),
            spotpy.parameter.List(self.param_names[4], self.behavioural_params[:, 4]),
            spotpy.parameter.List(self.param_names[5], self.behavioural_params[:, 5]),
            spotpy.parameter.List(self.param_names[6], self.behavioural_params[:, 6]),
            spotpy.parameter.List(self.param_names[7], self.behavioural_params[:, 7]),
            spotpy.parameter.List(self.param_names[8], self.behavioural_params[:, 8]),
            spotpy.parameter.List(self.param_names[9], self.behavioural_params[:, 9])
        ]
        # set up a database to custom save results
        self.database = file(self.model.out_f + '{}.SMART.glue'.format(catchment), 'wb')
        self.simu_steps = [dt.strftime("%Y-%m-%d %H:%M:%S") for dt in self.model.flow.iterkeys()] \
            if self.save_sim else []
        # write header in database file
        self.database.write(','.join(self.obj_fn_names + self.param_names + self.simu_steps) + '\n')

    def parameters(self):
        # returns an ndarray containing a tuple for each parameter (random value, step, optguess, minbound, maxbound)
        # parameter.generate() loops through each Object in self.params
        # and uses its astuple() method (inherited from the Base class)
        # that itself uses its __call__() (also inherited from the Base class)
        return spotpy.parameter.generate(self.params)

    def simulation(self, vector):
        simulations, constraint = self.model.simulate({
            'T': vector[0], 'C': vector[1], 'H': vector[2], 'D': vector[3], 'S': vector[4], 'Z': vector[5],
            'SK': vector[6], 'FK': vector[7], 'GK': vector[8], 'RK': vector[9]
        })
        # returns only simulations with observations
        return [
            [simulations[dt] for dt in self.model.flow.iterkeys()],
            [constraint]
        ]

    def evaluation(self):
        return [
            np.asarray([observation for observation in self.model.flow.itervalues()]),
            [self.constraints['gw']]
        ]

    def objectivefunction(self, simulation, evaluation):
        # select the series subset that have observations (i.e. not NaN)
        flow_eval = evaluation[0][~np.isnan(evaluation[0])]
        flow_simu = np.asarray(simulation[0])[~np.isnan(evaluation[0])]

        # calculate the objective functions
        obj1 = spotpy.objectivefunctions.nashsutcliffe(evaluation=flow_eval, simulation=flow_simu)
        obj2 = spotpy.objectivefunctions.lognashsutcliffe(evaluation=flow_eval, simulation=flow_simu)
        obj3 = sqrt_nash_sutcliffe(evaluation=flow_eval, simulation=flow_simu)
        obj4 = bounded_nash_sutcliffe(evaluation=flow_eval, simulation=flow_simu)
        obj5, obj5c, obj5a, obj5b = \
            spotpy.objectivefunctions.kge(evaluation=flow_eval, simulation=flow_simu, return_all=True)
        obj6 = spotpy.objectivefunctions.bias(evaluation=flow_eval, simulation=flow_simu)
        obj7 = spotpy.objectivefunctions.pbias(evaluation=flow_eval, simulation=flow_simu)
        obj8 = spotpy.objectivefunctions.rmse(evaluation=flow_eval, simulation=flow_simu)
        obj9 = spearman_rank_corr(evaluation=flow_eval, simulation=flow_simu)
        obj10 = mean_abs_rel_error(evaluation=flow_eval, simulation=flow_simu)
        obj11 = groundwater_constraint(evaluation=evaluation[1], simulation=simulation[1])

        if self.constraints['gw'] == -999.0:
            return [obj1, obj2, obj3, obj4, obj5, obj5c, obj5a, obj5b, obj6, obj7, obj8, obj9, obj10]
        else:
            return [obj1, obj2, obj3, obj4, obj5, obj5c, obj5a, obj5b, obj6, obj7, obj8, obj9, obj10, obj11]

    def save(self, obj_fns, parameters, simulations, *args, **kwargs):
        if self.save_sim:
            line = map(np.float32, obj_fns + parameters.tolist() + simulations[0])
        else:
            line = map(np.float32, obj_fns + parameters.tolist())
        self.database.write(','.join(map(str, line)) + '\n')


def get_sampled_sets_from_file(file_location, param_names, obj_fn_names):
    with open(file_location) as my_file:
        my_reader = DictReader(my_file)
        obj_fns, params = list(), list()
        for row in my_reader:
            obj_fns.append([row[obj_fn] for obj_fn in obj_fn_names])
            params.append([row[param] for param in param_names])

    return np.array(params, dtype=np.float64), np.array(obj_fns, dtype=np.float64)


def get_behavioural_sets(params, obj_fns, conditions_val, conditions_typ):

    if obj_fns.ndim != 2:
        raise Exception('The matrix containing the objective functions is not 2D.')
    if params.ndim != 2:
        raise Exception('The matrix containing the parameters is not 2D.')
    if obj_fns.shape[0] != params.shape[0]:
        raise Exception('The matrices containing objective functions and parameters have different sample sizes.')
    if not ((obj_fns.shape[1] == len(conditions_val)) and (obj_fns.shape[1] == len(conditions_typ))):
        raise Exception('The objective function matrix and the conditions matrices '
                        'do not have compatible dimensions.')

    behavioural = np.ones((obj_fns.shape[0],), dtype=bool)
    for obj_fn, values, kind in izip(obj_fns.T, conditions_val, conditions_typ):
        if kind == 'equal':
            if len(values) == 1:
                selection = obj_fn == values[0]
            else:
                raise Exception("The tuple for \"equal\" condition does not contain one and only one element.")
        elif kind == 'min':
            if len(values) == 1:
                selection = obj_fn >= values[0]
            else:
                raise Exception("The tuple for \"min\" condition does not contain one and only one element.")
        elif kind == 'max':
            if len(values) == 1:
                selection = obj_fn <= values[0]
            else:
                raise Exception("The tuple for \"max\" condition does not contain one and only one element.")
        elif kind == 'inside':
            if len(values) == 2:
                if values[1] > values[0]:
                    selection = (obj_fn >= values[0]) & (obj_fn <= values[1])
                else:
                    raise Exception("The two elements of the tuple for \"inside\" are inconsistent.")
            else:
                raise Exception("The tuple for \"inside\" condition does not contain two and only two elements.")
        elif kind == 'outside':
            if len(values) == 2:
                if values[1] > values[0]:
                    selection = (obj_fn <= values[0]) & (obj_fn >= values[1])
                else:
                    raise Exception("The two elements of the tuple for \"outside\" are inconsistent.")
            else:
                raise Exception("The tuple for \"outside\" condition does not contain two and only two elements.")
        else:
            raise Exception("The type of threshold \"{}\" is not in the database.".format(kind))

        behavioural *= selection

    return params[behavioural, :]


def spotpy_instructions(catchment, parallel, root_f):

    spotpy_setup = SpotPySetUp(catchment, root_f, save_sim=True)

    sampler = spotpy.algorithms.mc(spotpy_setup, parallel=parallel)

    sampler.sample(spotpy_setup.behavioural_params.shape[0])


if __name__ == '__main__':
    # Define the root of the SMARTpy package
    if getcwd() == path.dirname(path.realpath(__file__)):  # execution from the directory where the script is
        smart_root = path.realpath('../..')  # move to parent of parent directory of this current python file
    else:  # execution not from the directory where the script is
        smart_root = getcwd()  # keep the current working directory

    # Collect the arguments to set up SPOTPY
    parser = argparse.ArgumentParser(description="simulate lumped catchment hydrology"
                                                 "for one catchment and one time period"
                                                 "using SPOTPY")
    parser.add_argument('catchment', type=str,
                        help="name of the catchment")
    parser.add_argument('-s', '--sequence', dest='parallelisation', action='store_false',
                        help="compute each sample in sequence ")
    parser.add_argument('-p', '--parallel', dest='parallelisation', action='store_true',
                        help="parallel computing of the sample  ")
    parser.set_defaults(parallelisation=False)
    args_ = parser.parse_args()

    # send the relevant argument for parallelisation option
    if args_.parallelisation:
        parallelisation = 'mpi'  # use MPI and parallel computing
    else:
        parallelisation = 'seq'  # use traditional sequential computing

    # Call main function containing SPOTPY instructions
    spotpy_instructions(args_.catchment, parallelisation, smart_root)
