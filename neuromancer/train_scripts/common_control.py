import argparse

import torch
import torch.nn.functional as F
from torch import nn

import slim
from neuromancer import loggers
from neuromancer.datasets import EmulatorDataset, FileDataset, systems
from neuromancer import blocks
from neuromancer import dynamics
from neuromancer import estimators
from neuromancer.problem import Problem, Objective
from neuromancer.activations import BLU, SoftExponential
from neuromancer import policies


def get_base_parser_control():
    parser = argparse.ArgumentParser()
    parser.add_argument('-gpu', type=int, default=None,
                        help="Gpu to use")
    ##################
    # OPTIMIZATION PARAMETERS
    opt_group = parser.add_argument_group('OPTIMIZATION PARAMETERS')
    opt_group.add_argument('-epochs', type=int, default=100)
    opt_group.add_argument('-lr', type=float, default=0.001,
                           choices=[3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 0.01],
                           help='Step size for gradient descent.')
    opt_group.add_argument('-patience', type=int, default=100,
                           help='How many epochs to allow for no improvement in eval metric before early stopping.')
    opt_group.add_argument('-warmup', type=int, default=100,
                           help='Number of epochs to wait before enacting early stopping policy.')
    opt_group.add_argument('-skip_eval_sim', action='store_true',
                           help='Whether to run simulator during evaluation phase of training.')
    #################
    # DATA PARAMETERS
    data_group = parser.add_argument_group('DATA PARAMETERS')
    data_group.add_argument('-nsteps', type=int, default=32, choices=[4, 8, 16, 32, 64],
                            help='Number of steps for open loop during training.')
    data_group.add_argument('-system', type=str, default='flexy_air',
                            help='select particular dataset with keyword')
    data_group.add_argument('-nsim', type=int, default=100000,
                            help='Number of time steps for full dataset. (ntrain + ndev + ntest)'
                                 'train, dev, and test will be split evenly from contiguous, sequential, '
                                 'non-overlapping chunks of nsim datapoints, e.g. first nsim/3 art train,'
                                 'next nsim/3 are dev and next nsim/3 simulation steps are test points.'
                                 'None will use a default nsim from the selected dataset or emulator')
    data_group.add_argument('-norm', nargs='+', default=['U', 'D', 'Y'], choices=['U', 'D', 'Y', 'X'],
                            help='List of sequences to max-min normalize')

    # TODO: option with loading trained model
    # mfiles = ['models/best_model_flexy1.pth',
    #           'models/best_model_flexy2.pth',
    #           'ape_models/best_model_blocknlin.pth']
    # data_group.add_argument('-model_file', type=str, default=mfiles[0])

    ##################
    # POLICY PARAMETERS
    policy_group = parser.add_argument_group('POLICY PARAMETERS')
    policy_group.add_argument('-policy', type=str,
                              choices=['mlp', 'linear'], default='mlp')
    policy_group.add_argument('-n_hidden', type=int, default=20, choices=list(range(5, 50, 5)),
                              help='Number of hidden states')
    policy_group.add_argument('-n_layers', type=int, default=3, choices=list(range(1, 10)),
                              help='Number of hidden layers of single time-step state transition')
    policy_group.add_argument('-bias', action='store_true', help='Whether to use bias in the neural network models.')
    policy_group.add_argument('-policy_features', nargs='+', default=['Y_ctrl_p', 'Rf'],
                              help='Policy features')  # reference tracking option
    # TODO: generate constraints for the rest of datasets from psl
    # policy_group.add_argument('-policy_features', nargs='+', default=['Y_ctrl_p', 'Rf', 'Y_maxf', 'Y_minf'],
    #                           help='Policy features')  # reference tracking with constraints option

    policy_group.add_argument('-activation', choices=['gelu', 'softexp'], default='gelu',
                              help='Activation function for neural networks')
    policy_group.add_argument('-perturbation', choices=['white_noise_sine_wave', 'white_noise'], default='white_noise')

    ##################
    # LINEAR PARAMETERS
    linear_group = parser.add_argument_group('LINEAR PARAMETERS')
    linear_group.add_argument('-linear_map', type=str,
                              choices=['linear', 'softSVD', 'pf'],
                              default='linear')
    linear_group.add_argument('-sigma_min', type=float, choices=[1e-5, 0.1, 0.2, 0.3, 0.4, 0.5], default=0.1)
    linear_group.add_argument('-sigma_max', type=float, choices=[0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3],
                              default=1.0)
    ##################
    # LAYERS
    layers_group = parser.add_argument_group('LAYERS PARAMETERS')
    # TODO: generalize freeze unfreeze - we want to unfreeze only policy network
    layers_group.add_argument('-freeze', nargs='+', default=[''], help='sets requires grad to False')
    layers_group.add_argument('-unfreeze', default=['components.2'],
                              help='sets requires grad to True')

    ##################
    # WEIGHT PARAMETERS
    weight_group = parser.add_argument_group('WEIGHT PARAMETERS')
    weight_group.add_argument('-Q_con_x', type=float, default=1.0, choices=[0.1, 1.0, 10.0, 100.0],
                              help='Hidden state constraints penalty weight.')
    weight_group.add_argument('-Q_con_y', type=float, default=2.0, choices=[0.1, 1.0, 10.0, 100.0],
                              help='Observable constraints penalty weight.')
    weight_group.add_argument('-Q_dx', type=float, default=0.1, choices=[0.1, 1.0, 10.0, 100.0],
                              help='Penalty weight on hidden state difference in one time step.')
    weight_group.add_argument('-Q_sub', type=float, default=0.1, help='Linear maps regularization weight.',
                              choices=[0.1, 1.0, 10.0])
    weight_group.add_argument('-Q_y', type=float, default=1.0, choices=[0.1, 1.0, 10.0, 100.0],
                              help='Output tracking penalty weight')
    weight_group.add_argument('-Q_e', type=float, default=1.0, choices=[0.1, 1.0, 10.0, 100.0],
                              help='State estimator hidden prediction penalty weight')
    weight_group.add_argument('-Q_con_fdu', type=float, default=0.0, choices=[0.1, 1.0, 10.0, 100.0],
                              help='Penalty weight on control actions and disturbances.')
    weight_group.add_argument('-Q_con_u', type=float, default=10.0, choices=[0.1, 1.0, 10.0, 100.0],
                              help='Input constraints penalty weight.')
    weight_group.add_argument('-Q_r', type=float, default=1.0, choices=[0.1, 1.0, 10.0, 100.0],
                              help='Reference tracking penalty weight')
    weight_group.add_argument('-Q_du', type=float, default=0.1, choices=[0.1, 1.0, 10.0, 100.0],
                              help='control action difference penalty weight')
    # objective and constraints variations
    weight_group.add_argument('-con_tighten', choices=[0, 1], default=0)
    weight_group.add_argument('-tighten', type=float, default=0.05, choices=[0.1, 0.05, 0.01, 0.0],
                              help='control action difference penalty weight')
    weight_group.add_argument('-loss_clip', choices=[0, 1], default=0)
    weight_group.add_argument('-noise', choices=[0, 1], default=0)

    ####################
    # LOGGING PARAMETERS
    log_group = parser.add_argument_group('LOGGING PARAMETERS')
    log_group.add_argument('-savedir', type=str, default='test',
                           help="Where should your trained model and plots be saved (temp)")
    log_group.add_argument('-verbosity', type=int, default=1,
                           help="How many epochs in between status updates")
    log_group.add_argument('-exp', type=str, default='test',
                           help='Will group all run under this experiment name.')
    log_group.add_argument('-location', type=str, default='mlruns',
                           help='Where to write mlflow experiment tracking stuff')
    log_group.add_argument('-run', type=str, default='neuromancer',
                           help='Some name to tell what the experiment run was about.')
    log_group.add_argument('-logger', type=str, default='mlflow',
                           help='Logging setup to use')
    log_group.add_argument('-id', help='Unique run name')
    log_group.add_argument('-parent', help='ID of parent or none if from the Eve generation')
    log_group.add_argument('-train_visuals', action='store_true',
                           help='Whether to create visuals, e.g. animations during training loop')
    log_group.add_argument('-trace_movie', action='store_true',
                           help='Whether to plot an animation of the simulated and true dynamics')
    return parser


def get_policy_components(args, dataset, dynamics_model, policy_name="policy"):
    torch.manual_seed(args.seed)
    # control policy setup
    activation = {'gelu': nn.GELU,
                  'relu': nn.ReLU,
                  'blu': BLU,
                  'softexp': SoftExponential}[args.activation]
    linmap = slim.maps[args.linear_map]
    nh_policy = args.n_hidden
    policy = {'linear': policies.LinearPolicy,
              'mlp': policies.MLPPolicy,
              'rnn': policies.RNNPolicy
              }[args.policy]({'x0_estim': (dynamics_model.nx,), **dataset.dims},
                             nsteps=args.nsteps,
                             bias=args.bias,
                             linear_map=linmap,
                             nonlin=activation,
                             hsizes=[nh_policy] * args.n_layers,
                             input_keys=args.policy_features,
                             linargs={'sigma_min': args.sigma_min, 'sigma_max': args.sigma_max},
                             name=policy_name)
    return policy

def get_objective_terms_control(args, policy):
    if args.noise:
        output_key = 'Y_pred_dynamics_noise'
    else:
        output_key = 'Y_pred_dynamics'

    reference_loss = Objective([output_key, 'Rf'], lambda pred, ref: F.mse_loss(pred[:, :, :1], ref),
                               weight=args.Q_r, name='ref_loss')
    regularization = Objective([f'reg_error_{policy.name}'], lambda reg: reg,
                               weight=args.Q_sub)
    control_smoothing = Objective([f'U_pred_{policy.name}'], lambda x: F.mse_loss(x[1:], x[:-1]),
                                  weight=args.Q_du, name='control_smoothing')
    observation_lower_bound_penalty = Objective([output_key, 'Y_minf'],
                                                lambda x, xmin: torch.mean(F.relu(-x[:, :, :1] + xmin)),
                                                weight=args.Q_con_y, name='observation_lower_bound')
    observation_upper_bound_penalty = Objective([output_key, 'Y_maxf'],
                                                lambda x, xmax: torch.mean(F.relu(x[:, :, :1] - xmax)),
                                                weight=args.Q_con_y, name='observation_upper_bound')
    inputs_lower_bound_penalty = Objective([f'U_pred_{policy.name}', 'U_minf'], lambda x, xmin: torch.mean(F.relu(-x + xmin)),
                                           weight=args.Q_con_u, name='input_lower_bound')
    inputs_upper_bound_penalty = Objective([f'U_pred_{policy.name}', 'U_maxf'], lambda x, xmax: torch.mean(F.relu(x - xmax)),
                                           weight=args.Q_con_u, name='input_upper_bound')

    # Constraints tightening
    if args.con_tighten:
        observation_lower_bound_penalty = Objective([output_key, 'Y_minf'],
                                                    lambda x, xmin: torch.mean(F.relu(-x[:, :, :1] + xmin+args.tighten)),
                                                    weight=args.Q_con_y, name='observation_lower_bound')
        observation_upper_bound_penalty = Objective([output_key, 'Y_maxf'],
                                                    lambda x, xmax: torch.mean(F.relu(x[:, :, :1] - xmax+args.tighten)),
                                                    weight=args.Q_con_y, name='observation_upper_bound')
        inputs_lower_bound_penalty = Objective([f'U_pred_{policy.name}', 'U_minf'], lambda x, xmin: torch.mean(F.relu(-x + xmin+args.tighten)),
                                               weight=args.Q_con_u, name='input_lower_bound')
        inputs_upper_bound_penalty = Objective([f'U_pred_{policy.name}', 'U_maxf'], lambda x, xmax: torch.mean(F.relu(x - xmax+args.tighten)),
                                               weight=args.Q_con_u, name='input_upper_bound')

    # LOSS clipping
    if args.loss_clip:
        reference_loss = Objective([output_key, 'Rf', 'Y_minf', 'Y_maxf'],
                                   lambda pred, ref, xmin, xmax: F.mse_loss(pred[:, :, :1]*torch.gt(ref, xmin).int()*torch.lt(ref, xmax).int(), ref*torch.gt(ref, xmin).int()*torch.lt(ref, xmax).int()),
                                   weight=args.Q_r, name='ref_loss')

    objectives = [regularization, reference_loss]
    constraints = [observation_lower_bound_penalty, observation_upper_bound_penalty,
                   inputs_lower_bound_penalty, inputs_upper_bound_penalty]

    return objectives, constraints