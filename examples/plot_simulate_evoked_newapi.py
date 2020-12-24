"""
====================================
Simulate dipole using new drives-API
====================================

This example demonstrates how to simulate a dipole for evoked-like
waveforms using HNN-core.

Note that the output will be slightly different from HNN-GUI due to different
"seeds" being used when creating the random exogeneous input spikes to the
network. The results should match qualitatively, however.
"""

# Authors: Mainak Jas <mainak.jas@telecom-paristech.fr>
#          Sam Neymotin <samnemo@gmail.com>
#          Blake Caldwell <blake_caldwell@brown.edu>
#          Christopher Bailey <cjb@cfin.au.dk>

import os.path as op
import tempfile

###############################################################################
# Let us import hnn_core

import hnn_core
from hnn_core import simulate_dipole, read_params, Network, read_spikes
from hnn_core.viz import plot_dipole

hnn_core_root = op.dirname(hnn_core.__file__)

###############################################################################
# Then we read the parameters file
params_fname = op.join(hnn_core_root, 'param', 'default.json')
params = read_params(params_fname)
print(params)

###############################################################################
# This is a lot of parameters! We can also filter the
# parameters using unix-style wildcard characters
print(params['L2Pyr_soma*'])

###############################################################################
# Let us first create our network from the params file and visualize the cells
# inside it. The default behaviour of Network is to add and instantiate six
# 'default' drives, but we will suppress that by setting the
# `initialise_hnn_drives`-argument to `False`.
net = Network(params, initialise_hnn_drives=False)
net.plot_cells()

###############################################################################
# The network of cells is now defined, to which we add external drives as
# required. Weights are prescribed separately for AMPA and NMDA receptors
# (receptors that are not used can be omitted or set to zero)

# Two "silent" bursty drives (not connected, but affect seeds via gid assgnmt)
for ii in range(2):
    weights_ampa = {}
    weights_nmda = {}
    dispersion_time = 0.1
    net.add_bursty_drive(
        f'bursty{ii + 1}', distribution='normal', t0=0, sigma_t0=1., T=1.,
        burst_f=10, burst_sigma_f=2., numspikes=2, repeats=20,
        weights_ampa=weights_ampa, weights_nmda=weights_nmda,
        location='distal', seedcore=2,
        space_constant=3., dispersion_time=dispersion_time)

# Distal evoked drive
weights_ampa = {'L2_basket': 0.006562, 'L2_pyramidal': .000007,
                'L5_pyramidal': 0.142300}
weights_nmda = {'L2_basket': 0.019482, 'L2_pyramidal': 0.004317,
                'L5_pyramidal': 0.080074}
dispersion_time = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                   'L5_pyramidal': 0.1}
net.add_evoked_drive(
    'evdist1', mu=63.53, sigma=3.85, numspikes=1, weights_ampa=weights_ampa,
    weights_nmda=weights_nmda, location='distal', seedcore=2,
    space_constant=3., dispersion_time=dispersion_time)

# First proximal evoked drive
weights_ampa = {'L2_basket': 0.08831, 'L2_pyramidal': 0.01525,
                'L5_basket': 0.19934, 'L5_pyramidal': 0.00865}
weights_nmda = {'L2_basket': 0., 'L2_pyramidal': 0.,
                'L5_basket': 0., 'L5_pyramidal': 0.}  # all weights zero
dispersion_time = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                   'L5_basket': 1., 'L5_pyramidal': 1.}
net.add_evoked_drive(
    'evprox1', mu=26.61, sigma=2.47, numspikes=1, weights_ampa=weights_ampa,
    weights_nmda=weights_nmda, location='proximal', seedcore=2,
    space_constant=3., dispersion_time=dispersion_time)

# Second proximal evoked drive
weights_ampa = {'L2_basket': 0.000003, 'L2_pyramidal': 1.438840,
                'L5_basket': 0.008958, 'L5_pyramidal': 0.684013}
weights_nmda = {}  # all weights zero: pass an empty dict to the add-method
dispersion_time = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                   'L5_basket': 1., 'L5_pyramidal': 1.}
net.add_evoked_drive(
    'evprox2', mu=137.12, sigma=8.33, numspikes=1, weights_ampa=weights_ampa,
    weights_nmda=weights_nmda, location='proximal', seedcore=2,
    space_constant=3., dispersion_time=dispersion_time)

###############################################################################
# Now let's simulate the dipole, running 2 trials with the Joblib backend.
# To run them in parallel we could set n_jobs to equal the number of trials.
from hnn_core import JoblibBackend

with JoblibBackend(n_jobs=1):
    dpls = simulate_dipole(net, n_trials=2, postproc=True)

###############################################################################
# and then plot it
import matplotlib.pyplot as plt
fig, axes = plt.subplots(2, 1, sharex=True, figsize=(6, 6))
plot_dipole(dpls, ax=axes[0], layer='agg', show=False)
net.cell_response.plot_spikes_hist(ax=axes[1],
                                   spike_types=['evprox', 'evdist'])

###############################################################################
# Also, we can plot the spikes and write them to txt files.
# Note that we can use formatting syntax to specify the filename pattern
# with which each trial will be written. To read spikes back in, we can use
# wildcard expressions.
net.cell_response.plot_spikes_raster()
with tempfile.TemporaryDirectory() as tmp_dir_name:
    net.cell_response.write(op.join(tmp_dir_name, 'spk_%d.txt'))
    cell_response = read_spikes(op.join(tmp_dir_name, 'spk_*.txt'))
cell_response.plot_spikes_raster()

###############################################################################
# We can additionally calculate the mean spike rates for each cell class by
# specifying a time window with tstart and tstop.
all_rates = cell_response.mean_rates(tstart=0, tstop=170,
                                     gid_ranges=net.gid_ranges,
                                     mean_type='all')
trial_rates = cell_response.mean_rates(tstart=0, tstop=170,
                                       gid_ranges=net.gid_ranges,
                                       mean_type='trial')
print('Mean spike rates across trials:')
print(all_rates)
print('Mean spike rates for individual trials:')
print(trial_rates)

###############################################################################
# Now, let us try to make the exogenous driving inputs to the cells
# synchronous and see what happens. This is achieved by setting sigma=0.

net_sync = Network(params, initialise_hnn_drives=False)

# Two "silent" bursty drives (not connected, but affect seeds via gid assgnmt)
for ii in range(2):
    weights_ampa = {}
    weights_nmda = {}
    dispersion_time = 0.1
    net_sync.add_bursty_drive(
        f'bursty{ii + 1}', distribution='normal', t0=0, sigma_t0=1., T=1.,
        burst_f=10, burst_sigma_f=2., numspikes=2, repeats=20,
        weights_ampa=weights_ampa, weights_nmda=weights_nmda,
        location='distal', seedcore=2,
        space_constant=3., dispersion_time=dispersion_time)

# Distal evoked drive
weights_ampa = {'L2_basket': 0.006562, 'L2_pyramidal': .000007,
                'L5_pyramidal': 0.142300}
weights_nmda = {'L2_basket': 0.019482, 'L2_pyramidal': 0.004317,
                'L5_pyramidal': 0.080074}
dispersion_time = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                   'L5_pyramidal': 0.1}
net_sync.add_evoked_drive(
    'evdist1', mu=63.53, sigma=0, numspikes=1, weights_ampa=weights_ampa,
    weights_nmda=weights_nmda, location='distal', seedcore=2,
    space_constant=3., dispersion_time=dispersion_time)

# First proximal evoked drive
weights_ampa = {'L2_basket': 0.08831, 'L2_pyramidal': 0.01525,
                'L5_basket': 0.19934, 'L5_pyramidal': 0.00865}
weights_nmda = {'L2_basket': 0., 'L2_pyramidal': 0.,
                'L5_basket': 0., 'L5_pyramidal': 0.}  # all weights zero
dispersion_time = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                   'L5_basket': 1., 'L5_pyramidal': 1.}
net_sync.add_evoked_drive(
    'evprox1', mu=26.61, sigma=0, numspikes=1, weights_ampa=weights_ampa,
    weights_nmda=weights_nmda, location='proximal', seedcore=2,
    space_constant=3., dispersion_time=dispersion_time)

# Second proximal evoked drive
weights_ampa = {'L2_basket': 0.000003, 'L2_pyramidal': 1.438840,
                'L5_basket': 0.008958, 'L5_pyramidal': 0.684013}
weights_nmda = {}  # all weights zero: pass an empty dict to the add-method
dispersion_time = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                   'L5_basket': 1., 'L5_pyramidal': 1.}
net_sync.add_evoked_drive(
    'evprox2', mu=137.12, sigma=0, numspikes=1, weights_ampa=weights_ampa,
    weights_nmda=weights_nmda, location='proximal', seedcore=2,
    space_constant=3., dispersion_time=dispersion_time)

###############################################################################
# Next, let's simulate a single trial using the MPI backend. This will
# start the simulation trial across the number of processors (cores)
# specified by n_procs using MPI. The 'mpiexec' launcher is for
# openmpi, which must be installed on the system
from hnn_core import MPIBackend

with MPIBackend(n_procs=2, mpi_cmd='mpiexec'):
    dpls_sync = simulate_dipole(net_sync, n_trials=1)

dpls_sync[0].plot()
net_sync.cell_response.plot_spikes_hist()