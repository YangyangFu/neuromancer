# NeuroMANCER

![UML diagram](figs/class_diagram.png)

## Setup

##### Clone and install neuromancer, linear maps, and emulator packages
```console
user@machine:~$ mkdir neuromancer; cd neuromancer
user@machine:~$ git clone -b key_fix_cleanup https://stash.pnnl.gov/scm/deepmpc/deepmpc.git
user@machine:~$ git clone https://stash.pnnl.gov/scm/deepmpc/slip.git
user@machine:~$ git clone https://stash.pnnl.gov/scm/deepmpc/slim.git
```

##### Create the environment via .yml (Linux)

```console
user@machine:~$ conda env create -f env.yml
(neuromancer) user@machine:~$ source activate neuromancer
```

##### Create the environment manually

```console
user@machine:~$ conda config --add channels conda-forge pytorch
user@machine:~$ conda create -n neuromancer python=3.7
user@machine:~$ source activate neuromancer
(neuromancer) user@machine:~$ conda install pytorch torchvision cudatoolkit=9.0 -c pytorch
(neuromancer) user@machine:~$ conda install scipy pandas matplotlib control pyts numba scikit-learn mlflow dill
(neuromancer) user@machine:~$ conda install -c powerai gym
```

### install neuromancer ecosystem 

```console
(neuromancer) user@machine:~$ cd slip
(neuromancer) user@machine:~$ python setup.py develop
(neuromancer) user@machine:~$ cd ../slim
(neuromancer) user@machine:~$ python setup.py develop
(neuromancer) user@machine:~$ cd ../deepmpc
(neuromancer) user@machine:~$ python setup.py develop
```

