"""
wrapper for emulator dynamical models
Internal Emulators - in house ground truth equations
External Emulators - third party models
"""

from scipy.io import loadmat
from abc import ABC, abstractmethod
import numpy as np
import plot

####################################
###### Internal Emulators ##########
####################################

class EmulatorBase(ABC):
    """
    base class of the emulator
    """
    def __init__(self):
        super().__init__()

    # # TODO: not sure we need inputs/outputs as separate functions
    # # inputs of the dynamical system
    # @abstractmethod
    # def inputs(self):
    #     pass
    #
    # # outputs of the dynamical system
    # @abstractmethod
    # def outputs(self):
    #     pass

    # parameters of the dynamical system
    @abstractmethod
    def parameters(self, **kwargs):
        pass

    # equations defining the dynamical system
    @abstractmethod
    def equations(self, **kwargs):
        pass

    # # single forward time step of the dynamical system
    # @abstractmethod
    # def step(self):
    #     pass

    # N-step forward simulation of the dynamical system
    @abstractmethod
    def simulate(self, **kwargs):
        pass


class LTISSM(EmulatorBase):
    """
    base class of the linear time invariant state space model
    """
    def __init__(self):
        super().__init__()
        pass

class LTVSSM(EmulatorBase):
    """
    base class of the linear time varying state space model
    """
    def __init__(self):
        super().__init__()
        pass


class LPVSSM(EmulatorBase):
    """
    base class of the linear parameter varying state space model
    """
    def __init__(self):
        super().__init__()
        pass


class Building_hf(EmulatorBase):
    """
    building model with linear state dynamics and bilinear heat flow input dynamics
    parameters obtained from the original white-box Modelica model
    """
    def __init__(self):
        super().__init__()

    # parameters of the dynamical system
    def parameters(self, file_path='./emulators/buildings/Reno_model_for_py.mat'):
        file = loadmat(file_path)

        #  LTI SSM model
        self.A = file['Ad']
        self.B = file['Bd']
        self.C = file['Cd']
        self.D = file['Dd']
        self.E = file['Ed']
        self.G = file['Gd']
        self.F = file['Fd']

        self.Ts = file['Ts']  # sampling time
        self.TSup = file['TSup']  # supply temperature
        self.umax = file['umax']  # max heat per zone
        self.umin = file['umin']  # min heat per zone

        #         heat flow equation constants
        self.rho = 0.997  # density  of water kg/1l
        self.cp = 4185.5  # specific heat capacity of water J/(kg/K)
        self.time_reg = 1 / 3600  # time regularization of the mass flow 1 hour = 3600 seconds

        # problem dimensions
        self.nx = self.A.shape[0]
        self.ny = self.C.shape[0]
        self.nu = self.B.shape[1]
        self.nd = self.E.shape[1]
        self.n_mf = self.B.shape[1]
        self.n_dT = 1

        self.x0 = 0 * np.ones(self.nx, dtype=np.float32)  # initial conditions
        self.D = file['disturb'] # pre-defined disturbance profiles
    #     TODO: pre defined inputs?

    # equations defining single step of the dynamical system
    def equations(self, x, m_flow, dT, d):
        u = m_flow * self.rho * self.cp * self.time_reg * dT
        x = np.matmul(self.A, x) + np.matmul(self.B, u) + np.matmul(self.E, d) + self.G.ravel()
        y = np.matmul(self.C, x) + self.F.ravel()
        return u, x, y

    # N-step forward simulation of the dynamical system
    def simulate(self, ninit, nsim, M_flow, DT, D=None, x0=None):
        """
        :param nsim: (int) Number of steps for open loop response
        :param M_flow: (ndarray, shape=(nsim, self.n_mf)) mass flow profile matrix
        :param DT: (ndarray, shape=(nsim, self.n_dT)) temperature difference profile matrix
        :param D: (ndarray, shape=(nsim, self.nd)) measured disturbance signals
        :param x: (ndarray, shape=(self.nx)) Initial state. If not give will use internal state.
        :return: The response matrices, i.e. U, X, Y, for heat flows, states, and output ndarrays
        """
        if x0 is None:
            x = self.x0
        else:
            assert x0.shape[0] == self.nx, "Mismatch in x0 size"
            x = x0

        if D is None:
            D = self.D[ninit: ninit+nsim,:]

        U, X, Y = [], [], []
        N = 0
        for m_flow, dT, d in zip(M_flow, DT, D):
            N += 1
            u, x, y = self.equations(x, m_flow, dT, d)
            U.append(u)
            X.append(x + 20)  # updated states trajectories with initial condition 20 deg C of linearization
            Y.append(y - 273.15)  # updated input trajectories from K to deg C
            if N == nsim:
                break
        return np.asarray(U), np.asarray(X), np.asarray(Y)



##############################################
###### External Emulators Interface ##########
##############################################
# TODO: interface with, e.g., OpenAI gym



##########################################################
###### Base Control Profiles for System excitation #######
##########################################################
# TODO: functions generating baseline control signals or noise used for exciting the system for system ID and RL

def PRBS(nx,nsim):
    """
    pseudo random binary signal
    :param nx: (int) Number signals
    :param nsim: (int) Number time steps
    """
    pass

def WhiteNoise():
    """
    White Noise
    :param nx: (int) Number signals
    :param nsim: (int) Number time steps
    """
    pass

def Step():
    """
    step change
    :param nx: (int) Number signals
    :param nsim: (int) Number time steps
    """
    pass

def Ramp():
    """
    ramp change
    :param nx: (int) Number signals
    :param nsim: (int) Number time steps
    """
    pass

def Periodic(nx, nsim, numPeriods=1, xmax=1, xmin=0, type='sine'):
    """
    periodic signals, sine, cosine
    :param nx: (int) Number signals
    :param nsim: (int) Number time steps
    :param periods: (int) Number of periods
    """

    # x = np.linspace(0, numPeriods, nsim)
    # freq = nsim / numPeriods
    # ampl = xmax-xmin
    # freq = 1
    # f1 = lambda x: ampl* np.sin(freq * 2 * np.pi * x)
    # sampled_f1 = np.asarray([f1(i) for i in x])

    # TODO: finish
    samples_period = nsim// numPeriods
    leftover = nsim % numPeriods

    if type == 'sin':
        base_wave = (0.5 + 0.5 * np.sin(np.arange(0, 2 * np.pi, 2 * np.pi / samples_period)))
    elif type == 'cos':
        base_wave = (0.5 + 0.5 * np.cos(np.arange(0, 2 * np.pi, 2 * np.pi / samples_period)))

    # X = Xmin + Xmax * base_wave
    # M_flow = np.matlib.repmat(m_flow_day, 1, sim_days).T
    # return X
    pass

def SignalComposite():
    """
    composite of signal excitations
    allows generating heterogenous signals
    """
    pass

def SignalSeries():
    """
    series of signal excitations
    allows combining sequence of different signals
    """
    pass


if __name__ == '__main__':
    """
    Tests
    """
    ninit = 0
    nsim = 1000

    building = Building_hf()   # instantiate building class
    building.parameters()      # load model parameters

    M_flow = np.ones([100,building.n_mf])
    DT = np.ones([100,building.n_dT])
    D = building.D[ninit:nsim,:]
    U, X, Y = building.simulate(ninit, nsim, M_flow, DT, D)

    plot.pltOL(Y, U, D, X)
    plot.pltOL(Y, U, D)

