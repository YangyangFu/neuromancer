"""

policies for SSM models

    + x: states
    + u: control inputs
    + d: uncontrolled inputs (measured disturbances)
    + r: reference signals

generic mapping:

    + u = policy(x,u,d,r)
"""

# machine learning/data science imports
import torch
import torch.nn as nn

# ecosystem imports
import slim

# local imports
import neuromancer.blocks as blocks
from neuromancer.component import Component


class Policy(Component):
    DEFAULT_INPUT_KEYS = ["x0"]
    DEFAULT_OUTPUT_KEYS = ["U_pred", "reg_error"]

    def __init__(self, data_dims, nsteps=1, input_keys=["x0"], name="policy"):
        """

        :param data_dims: dict {str: tuple of ints) Data structure describing dimensions of input variables
        :param nsteps: (int) Prediction horizon
        :param input_keys: (List of str) List of input variable names
        :param name: (str) Name for tracking output of module.
        """
        self.DEFAULT_INPUT_KEYS = input_keys or self.DEFAULT_INPUT_KEYS
        super().__init__(name=name)

        self.name, self.data_dims = name, data_dims
        self.nsteps = nsteps
        self.data_dims = data_dims
        self.nu = data_dims["U"][-1]
        data_dims_in = {k: v for k, v in data_dims.items() if k in input_keys}
        self.sequence_dims_sum = sum(v[-1] for k, v in data_dims_in.items() if len(v) == 2)
        self.static_dims_sum = sum(v[-1] for k, v in data_dims_in.items() if len(v) == 1)
        self.in_features = self.static_dims_sum + nsteps * self.sequence_dims_sum
        self.out_features = nsteps * self.nu

    def reg_error(self):
        """

        :return: A scalar value of regularization error associated with submodules
        """
        error = sum([k.reg_error() for k in self.children() if hasattr(k, "reg_error")])
        if not isinstance(error, torch.Tensor):
            error = torch.Tensor(error)
        return error

    def features(self, data):
        """
        Compile a feature vector using data features corresponding to self.input_keys

        :param data: (dict {str: torch.Tensor})
        :return: (torch.Tensor)
        """
        featlist = []
        for k in self.input_keys:
            assert self.data_dims[k][-1] == data[k].shape[-1], \
                f"Input feature {k} expected {self.data_dims[k][-1]} but got {data[k].shape[-1]}"
            if len(data[k].shape) == 2:
                featlist.append(data[k])
            elif len(data[k].shape) == 3:
                assert len(data[k]) >= self.nsteps, \
                    f"Sequence too short for policy calculation. Should be at least {self.nsteps}"
                featlist.append(
                    torch.cat([step for step in data[k][:self.nsteps]], dim=1))
            else:
                raise ValueError(f"Input {k} has {len(data[k].shape)} dimensions. Should have 2 or 3 dimensions")
        return torch.cat(featlist, dim=1)

    def forward(self, data):
        """

        :param data: (dict {str: torch.tensor)}
        :return: (dict {str: torch.tensor)}
        """
        features = self.features(data)
        Uf = self.net(features)
        Uf = torch.cat([u.reshape(self.nsteps, 1, -1) for u in Uf], dim=1)
        return {"U_pred": Uf, "reg_error": self.reg_error()}


class Compensator(Policy):
    def __init__(self, data_dims, policy_output_keys, nsteps=1, input_keys=['Ep'], name='compensator'):
        """

        :param data_dims: dict {str: tuple of ints) Data structure describing dimensions of input variables
        :param policy_output_keys: output keys of the original policy to add upon
        :param nsteps: (int) Prediction horizon
        :param input_keys: (List of str) List of input variable names
        :param name: (str) Name for tracking output of module.
        """
        super().__init__(data_dims, nsteps=nsteps, input_keys=input_keys, name=name)
        self.policy_output_keys = policy_output_keys
        self.input_keys = input_keys
        assert len(input_keys) == 1, \
            f'One input key expected but got {len(input_keys)}. ' \
            f'Required format input_keys=[\'error signal\'].'

    def forward(self, data):
        """

        :param data: (dict {str: torch.tensor)}
        :return: (dict {str: torch.tensor)}
        """
        U_nominal = data[self.policy_output_keys]
        features = self.features(data)
        U_compensator = self.net(features)
        U_compensator = torch.cat([u.reshape(self.nsteps, 1, -1) for u in U_compensator], dim=1)
        # additive compensator for the nominal policy: e.g. for online updates
        Uf = U_nominal + U_compensator
        return {f'U_pred_{self.name}': Uf, f'reg_error_{self.name}': self.reg_error()}


class LinearCompensator(Compensator):
    def __init__(self, data_dims, policy_output_keys, nsteps=1, bias=False,
                 linear_map=slim.Linear, nonlin=None, hsizes=None,
                 input_keys=['Ep'], linargs=dict(), name='linear_compensator'):
        """

        :param data_dims:
        :param policy_output_keys: output keys of the original policy to add upon
        :param nsteps:
        :param bias:
        :param linear_map:
        :param nonlin:
        :param hsizes:
        :param input_keys:
        :param linargs:
        :param name:
        """
        super().__init__(data_dims, policy_output_keys, nsteps=nsteps, input_keys=input_keys, name=name)
        self.net = linear_map(self.in_features, self.out_features, bias=bias, **linargs)


class LinearPolicy(Policy):
    def __init__(self, data_dims, nsteps=1, bias=False,
                 linear_map=slim.Linear, nonlin=None, hsizes=None,
                 input_keys=["x0"], linargs=dict(), name="linear_policy"):
        """
        :param data_dims: dict {str: tuple of ints) Data structure describing dimensions of input variables
        :param nsteps: (int) Prediction horizon
        :param bias: (bool) Whether to use bias in MLP
        :param Linear: (class) slim.Linear class for subcomponents
        :param nonlin: (class) Pytorch elementwise activation function class for subcomponents
        :param hsizes: (List [int]) Sizes of hidden layers in MLP
        :param input_keys: (List of str) List of input variable names
        :param linargs: (dict) Arguments for instantiating linear layers.
        :param name: (str) Name for tracking output of module.
        """
        super().__init__(data_dims, nsteps=nsteps, input_keys=input_keys, name=name)
        self.net = linear_map(self.in_features, self.out_features, bias=bias, **linargs)


class MLPPolicy(Policy):
    def __init__(self, data_dims, nsteps=1, bias=False,
                 linear_map=slim.Linear, nonlin=nn.GELU, hsizes=[64],
                 input_keys=["x0"], linargs=dict(), name="MLP_policy"):
        """

        See LinearPolicy for arguments
        """
        super().__init__(data_dims, nsteps=nsteps, input_keys=input_keys, name=name)
        self.net = blocks.MLP(insize=self.in_features, outsize=self.out_features, bias=bias,
                              linear_map=linear_map, nonlin=nonlin, hsizes=hsizes, linargs=linargs)


class RNNPolicy(Policy):
    def __init__(self, data_dims, nsteps=1, bias=False,
                 linear_map=slim.Linear, nonlin=nn.GELU, hsizes=[64],
                 input_keys=["x0"], linargs=dict(), name="RNN_policy"):
        """
        See LinearPolicy for arguments
        """
        super().__init__(data_dims, nsteps=nsteps, input_keys=input_keys, name=name)
        self.in_features = self.sequence_dims_sum + self.static_dims_sum
        self.net = blocks.RNN(self.in_features, self.out_features, hsizes=hsizes,
                              bias=bias, nonlin=nonlin, linear_map=linear_map, linargs=linargs)

    def forward(self, data):
        """

        :param data: (dict {str: torch.tensor)}
        :return: (dict {str: torch.tensor)}
        """
        features = torch.cat([
            *[data[k][:self.nsteps] for k in self.input_keys if len(data[k].shape) == 3],
            *[data[k].expand(self.nsteps, -1, -1) for k in self.input_keys if len(data[k].shape) == 2],
        ], dim=2)

        Uf = self.net(features)
        Uf = torch.cat([u.reshape(self.nsteps, 1, -1) for u in Uf], dim=1)
        return {"U_pred": Uf, "reg_error": self.net.reg_error()}


policies = [LinearPolicy, MLPPolicy, RNNPolicy]


