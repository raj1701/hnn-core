"""
================================================
05. From MEG sensor-space data to HNN simulation
================================================

This example demonstrates how to calculate the inverse solution of the median
nerve evoked response in the MNE somatosensory dataset, and then simulate a
biophysical model network that reproduces the observed dynamics.
"""

# Authors: Mainak Jas <mainakjas@gmail.com>
#          Ryan Thorpe <ryan_thorpe@brown.edu>

# sphinx_gallery_thumbnail_number = 2

###############################################################################
# First, we will import the packages needed for computing the inverse solution
# from the MNE somatosensory dataset. `MNE`_ can be installed with
# ``pip install mne``, and the somatosensory dataset can be downloaded by
# importing ``somato`` from ``mne.datasets``.
import os.path as op
import numpy as np
import matplotlib.pyplot as plt

import mne
from mne.datasets import somato
from mne.minimum_norm import apply_inverse, make_inverse_operator

###############################################################################
# Now we set the the path of the ``somato`` dataset for subject ``'01'``.
data_path = somato.data_path()
subject = '01'
task = 'somato'
raw_fname = op.join(data_path, 'sub-{}'.format(subject), 'meg',
                    'sub-{}_task-{}_meg.fif'.format(subject, task))
fwd_fname = op.join(data_path, 'derivatives', 'sub-{}'.format(subject),
                    'sub-{}_task-{}-fwd.fif'.format(subject, task))
subjects_dir = op.join(data_path, 'derivatives', 'freesurfer', 'subjects')

###############################################################################
# Then, we load the raw data and estimate the inverse operator.

# Read and band-pass filter the raw data
raw = mne.io.read_raw_fif(raw_fname, preload=True)
raw.filter(1, 40)

# Identify stimulus events associated with MEG time series in the dataset
events = mne.find_events(raw, stim_channel='STI 014')

# Define epochs within the time series
event_id, tmin, tmax = 1, -.2, .17
baseline = None
epochs = mne.Epochs(raw, events, event_id, tmin, tmax, baseline=baseline,
                    reject=dict(grad=4000e-13, eog=350e-6), preload=True)

# Compute the inverse operator
fwd = mne.read_forward_solution(fwd_fname)
cov = mne.compute_covariance(epochs)
inv = make_inverse_operator(epochs.info, fwd, cov)

###############################################################################
# There are several methods to do source reconstruction. Some of the methods
# such as dSPM and MNE are distributed source methods whereas dipole fitting
# will estimate the location and amplitude of a single current dipole. At the
# moment, we do not offer explicit recommendations on which source
# reconstruction technique is best for HNN. However, we do want our users
# to note that the dipole currents simulated with HNN are assumed to be normal
# to the cortical surface. Hence, using the option ``pick_ori='normal'`` is
# appropriate.
snr = 3.
lambda2 = 1. / snr ** 2
evoked = epochs.average()
stc = apply_inverse(evoked, inv, lambda2, method='MNE',
                    pick_ori="normal", return_residual=False,
                    verbose=True)

# create label for the postcentral gyrus (S1) in source-space
hemi = 'rh'
label_tag = 'G_postcentral'
label_s1 = mne.read_labels_from_annot(subject, parc='aparc.a2009s', hemi=hemi,
                                      regexp=label_tag,
                                      subjects_dir=subjects_dir)[0]
stc_label = stc.in_label(label_s1)

###############################################################################
# We isolate the single most active vertex in the noise-corrected minimum norm
# estimate (dSPM) by calculating the L2 norm of the time course emerging at
# each vertex beginning at t=0.

# The time course from the minimum norm estimate (MNE) vertex with the greatest
# L2 norm represents the current dipole at a location of cortex with greatest
# response to stimulus. Let's now apply the MNE inverse solution and plot the
# time course of our selected vertex.

brain = stc_label.plot(subjects_dir=subjects_dir, hemi='rh', surface='white',
                       smoothing_steps='nearest', view_layout='horizontal',
                       backend='pyvista')
# note that adding a border to the rendered 3D object may not work with the
# matplotlib backend
brain.add_label(label_s1, borders=True)

# extract pca-flipped time course from S1
flip_data = stc.extract_label_time_course(label_s1, inv['src'],
                                          mode='pca_flip')
dipole_tc = -flip_data[0] * 1e9

plt.figure()
plt.plot(1e3 * stc.times, dipole_tc, 'ro--')
plt.xlabel('Time (ms)')
plt.ylabel('Current Dipole (nAm)')
plt.xlim((0, 170))
plt.axhline(0, c='k', ls=':')
plt.show()

###############################################################################
# If you wish to visualize the location and time course of the selected vertex
# in reference to the geometric structure of the cortex (i.e., plotted on a
# structural MRI), uncomment the code below. Note that in the HNN framework,
# positive and negative deflections of a current dipole source correspond to
# upwards (from deep to superficial) and downwards (from superficial to deep)
# current flow, respectively.
'''
brain = stc_mne.plot(subjects_dir=subjects_dir, hemi='rh', surface='white',
                     smoothing_steps='nearest', view_layout='horizontal')
vert_id = stc_mne.vertices[1][pick_vertex - len(stc_mne.vertices[0])]
brain.add_foci(vert_id, coords_as_verts=True, hemi='rh', color='green',
               scale_factor = 0.6, alpha=0.5)
'''

###############################################################################
# Now, let us try to simulate the same with ``hnn-core``. We read in the
# network parameters from ``N20.json`` and instantiate the network.

import hnn_core
from hnn_core import simulate_dipole, read_params, Network, MPIBackend
from hnn_core import average_dipoles

hnn_core_root = op.dirname(hnn_core.__file__)

params_fname = op.join(hnn_core_root, 'param', 'N20.json')
params = read_params(params_fname)

net = Network(params)

###############################################################################
# To simulate the source of the median nerve evoked response, we add a
# sequence of synchronous evoked drives: 1 proximal, 2 distal, and 1 final
# proximal drive. Note that setting ``sync_within_trial=True`` creates drives
# with synchronous input (arriving to and transmitted by hypothetical granular
# cells at the center of the network) to all pyramidal and basket cells that
# receive distal drive.

# Early proximal drive
weights_ampa_p = {'L2_basket': 0.0036, 'L2_pyramidal': 0.0039,
                  'L5_basket': 0.0019, 'L5_pyramidal': 0.0020}
weights_nmda_p = {'L2_basket': 0.0029, 'L2_pyramidal': 0.0005,
                  'L5_basket': 0.0030, 'L5_pyramidal': 0.0019}
synaptic_delays_p = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                     'L5_basket': 1.0, 'L5_pyramidal': 1.0}

net.add_evoked_drive(
    'evprox1', mu=20.0, sigma=3., numspikes=1, sync_within_trial=True,
    weights_ampa=weights_ampa_p, weights_nmda=weights_nmda_p,
    location='proximal', synaptic_delays=synaptic_delays_p, seedcore=6)

# Late proximal drive
weights_ampa_p = {'L2_basket': 0.003, 'L2_pyramidal': 0.0039,
                  'L5_basket': 0.004, 'L5_pyramidal': 0.0020}
weights_nmda_p = {'L2_basket': 0.001, 'L2_pyramidal': 0.0005,
                  'L5_basket': 0.002, 'L5_pyramidal': 0.0020}
synaptic_delays_p = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                     'L5_basket': 1.0, 'L5_pyramidal': 1.0}

net.add_evoked_drive(
    'evprox2', mu=130.0, sigma=3., numspikes=1, sync_within_trial=True,
    weights_ampa=weights_ampa_p, weights_nmda=weights_nmda_p,
    location='proximal', synaptic_delays=synaptic_delays_p, seedcore=6)

# Early distal drive
weights_ampa_d = {'L2_basket': 0.0043, 'L2_pyramidal': 0.0032,
                  'L5_pyramidal': 0.0009}
weights_nmda_d = {'L2_basket': 0.0029, 'L2_pyramidal': 0.0051,
                  'L5_pyramidal': 0.0010}
synaptic_delays_d = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                     'L5_pyramidal': 0.1}

net.add_evoked_drive(
    'evdist1', mu=32., sigma=3., numspikes=1, sync_within_trial=True,
    weights_ampa=weights_ampa_d, weights_nmda=weights_nmda_d,
    location='distal', synaptic_delays=synaptic_delays_d, seedcore=6)

# Late distal input
weights_ampa_d = {'L2_basket': 0.0041, 'L2_pyramidal': 0.0019,
                  'L5_pyramidal': 0.0018}
weights_nmda_d = {'L2_basket': 0.0032, 'L2_pyramidal': 0.0018,
                  'L5_pyramidal': 0.0017}
synaptic_delays_d = {'L2_basket': 0.1, 'L2_pyramidal': 0.1,
                     'L5_pyramidal': 0.1}

net.add_evoked_drive(
    'evdist2', mu=82., sigma=3., numspikes=1, sync_within_trial=True,
    weights_ampa=weights_ampa_d, weights_nmda=weights_nmda_d,
    location='distal', synaptic_delays=synaptic_delays_d, seedcore=2)

###############################################################################
# Now we run the simulation over 2 trials so that we can plot the average
# aggregate dipole. As in :ref:`the MPIBackend example
# <sphx_glr_auto_examples_plot_simulate_mpi_backend.py>`, we can use
# ``MPIBackend`` to reduce the simulation time by parallizing across cells in
# the network. However, no parallel backend is necessary. For a better
# match to the empirical waveform, set ``n_trials`` to be >=25.
n_trials = 2
# n_trials = 25
with MPIBackend(n_procs=2):
    dpls = simulate_dipole(net, n_trials=n_trials)

###############################################################################
# Finally, we plot the driving spike histogram, empirical and simulated median
# nerve evoked response waveforms, and output spike histogram.
fig, axes = plt.subplots(3, 1, sharex=True, figsize=(6, 6))
net.cell_response.plot_spikes_hist(ax=axes[0],
                                   spike_types=['evprox', 'evdist'],
                                   show=False)
axes[1].axhline(0, c='k', ls=':', label='_nolegend_')
axes[1].plot(1e3 * stc.times, dipole_tc, 'r--')
average_dipoles(dpls).plot(ax=axes[1], show=False)
axes[1].legend(['MNE vertex', 'HNN simulation'])
axes[1].set_ylabel('Current Dipole (nAm)')
net.cell_response.plot_spikes_raster(ax=axes[2])

###############################################################################
# .. LINKS
#
# .. _MNE: https://mne.tools/
