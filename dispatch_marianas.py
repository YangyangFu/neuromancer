import os
import argparse

parser = argparse.ArgumentParser()

parser.add_argument('-hours', type=int, help='number of gpu hours to request for job', default=24)
parser.add_argument('-partition', type=str, help='Partition of gpus to access', default='shared_dlt')
parser.add_argument('-allocation', type=str, help='Allocation name for billing', default='deepmpc')
parser.add_argument('-env', type=str, help='Name of conda environment for running code.', default='mpc2')
parser.add_argument('-results', type=str, help='Where to log mlflow results', default='/qfs/projects/deepmpc/mlflow/neurips_2020_exp/mlruns')
parser.add_argument('-exp_folder', type=str, help='Where to save sbatch scripts and log files',
                    default='sbatch/')
parser.add_argument('-nsamples', type=int, help='Number of samples for each experimental configuration',
                    default=10)

args = parser.parse_args()

template = '#!/bin/bash\n' +\
           '#SBATCH -A %s\n' % args.allocation +\
           '#SBATCH -t %s:00:00\n' % args.hours +\
           '#SBATCH --gres=gpu:1\n' +\
           '#SBATCH -p %s\n' % args.partition +\
           '#SBATCH -N 1\n' +\
           '#SBATCH -n 2\n' +\
           '#SBATCH -o %j.out\n' +\
           '#SBATCH -e %j.err\n' +\
           'source /etc/profile.d/modules.sh\n' +\
           'module purge\n' +\
           'module load python/anaconda3.2019.3\n' +\
           'ulimit\n' +\
           'source activate %s\n\n' % args.env


os.system('mkdir %s' % args.exp_folder)

datapaths = ['./datasets/NLIN_SISO_two_tank/NLIN_two_tank_SISO.mat',
                 './datasets/NLIN_MIMO_vehicle/NLIN_MIMO_vehicle3.mat',
                 './datasets/NLIN_MIMO_CSTR/NLIN_MIMO_CSTR2.mat',
                 './datasets/NLIN_MIMO_Aerodynamic/NLIN_MIMO_Aerodynamic.mat']
ssm_type=['BlockSSM', 'BlackSSM']
linear_map=['pf', 'spectral', 'linear']
nonlinear_map= ['mlp', 'sparse_residual_mlp', 'linear']

for path in datapaths:
    for linear in linear_map:
        for nonlinear in nonlinear_map:
            for nsteps in [2, 4, 8, 16, 32]:
                for i in range(args.nsamples): # 10 samples for each configuration
                    cmd = 'python train_loop.py ' +\
                          '-gpu 0 ' +\
                          '-epochs 30000 ' + \
                          '-location %s ' % args.results + \
                          '-datafile %s ' % path + \
                          '-linear_map %s ' % linear + \
                          '-nonlinear_map %s ' % nonlinear + \
                          '-nsteps %s ' % nsteps + \
                          '-exp %s_%s_%s ' % (linear, nonlinear, nsteps) # group experiments with same configuration together - TODO: add more params
                    with open(os.path.join(args.exp_folder, 'exp_%s_%s_%s_%s.slurm' % (linear, nonlinear, nsteps, i)), 'w') as cmdfile: # unique name for sbatch script
                        cmdfile.write(template + cmd)
