"""
Handler classes to calculate extracellular electric potentials, such as the
Local Field Potential (LFP), at ideal (point-like) electrodes based on net
transmembrane currents of all neurons in the network.

The code is inspired by [1], but important modifications were made to comply
with the original derivation [2] of the 'line source approximation method'.

References
----------
1 . Parasuram H, Nair B, D'Angelo E, Hines M, Naldi G, Diwakar S (2016)
Computational Modeling of Single Neuron Extracellular Electric Potentials and
Network Local Field Potentials using LFPsim. Front Comput Neurosci 10:65.
2. Holt, G. R. (1998) A critical reexamination of some assumptions and
   implications of cable theory in neurobiology. CalTech, PhD Thesis.
"""

# Authors: Mainak Jas <mjas@mgh.harvard.edu>
#          Nick Tolley <nicholas_tolley@brown.edu>
#          Sam Neymotin <samnemo@gmail.com>
#          Christopher Bailey <cjb@cfin.au.dk>

from neuron import h

from copy import deepcopy
import numpy as np
from .externals.mne import _validate_type, _check_option
from numpy.linalg import norm


def _get_sections_on_this_rank(sec_type='Pyr'):
    ls = h.allsec()
    ls = [s for s in ls if sec_type in s.name()]
    return ls


def _get_segment_counts(all_sections):
    """The segment count of a section excludes the endpoints (0, 1)"""
    seg_counts = list()
    for sec in all_sections:
        seg_counts.append(sec.nseg)
    return seg_counts


def _transfer_resistance(section, electrode_pos, sigma, method,
                         min_distance=0.5):
    """Transfer resistance between section and electrode position.

    To arrive at the extracellular potential, the value returned by this
    function is multiplied by the net transmembrane current flowing through all
    segments of the section. Hence the term "resistance" (voltage equals
    current times resistance).

    Parameters
    ----------
    section : h.Section()
        The NEURON section.
    electrode_pos : list (x, y, z)
        The x, y, z coordinates of the electrode (in um)
    sigma : float
        Extracellular conductivity (in S/m)
    method : str
        Approximation to use. ``'psa'`` (point source approximation) treats
        each segment junction as a point extracellular current source.
        ``'lsa'`` (line source approximation) treats each segment as a line
        source of current, which extends from the previous to the next segment
        center point: |---x---|, where x is the current segment flanked by |.
    min_distance : float (default: 0.5)
        To avoid numerical errors in the 1/R calculation, we'll by default
        limit the distance to 0.5 um, corresponding to 1 um diameter dendrites.
        NB: LFPy uses section.diam / 2.0, i.e., whatever the closest section
        radius happens to be. This may not make sense for HNN model neurons, in
        which dendrite diameters have been adjusted to represent the entire
        tree (Bush & Sejnowski, 1993).

    Returns
    -------
    vres : list
        The transfer resistance at each segment of the section.
    """
    electrode_pos = np.array(electrode_pos)  # electrode position to Numpy

    sec_start = np.array([section.x3d(0), section.y3d(0), section.z3d(0)])
    sec_end = np.array([section.x3d(1), section.y3d(1), section.z3d(1)])
    sec_vec = sec_end - sec_start

    # NB segment lengths aren't equal! First/last segment center point is
    # closer to respective end point than to next/previous segment!
    # for nseg == 5, the segment centers are: [0.1, 0.3, 0.5, 0.7, 0.9]
    seg_ctr = np.zeros((section.nseg, 3))
    line_lens = np.zeros((section.nseg + 2))
    for ii, seg in enumerate(section):
        seg_ctr[ii, :] = sec_start + seg.x * sec_vec
        line_lens[ii + 1] = seg.x * section.L
    line_lens[-1] = section.L
    line_lens = np.diff(line_lens)
    first_len = line_lens[0]
    line_lens = np.array([first_len] + list(line_lens[2:]))

    if method == 'psa':

        # distance from segment midpoints to electrode
        dis = norm(np.tile(electrode_pos, (section.nseg, 1)) - seg_ctr,
                   axis=1)

        # To avoid very large values when electrode is placed close to a
        # segment junction, enforce minimal radial distance
        dis = np.maximum(dis, min_distance)

        phi = 1. / dis

    elif method == 'lsa':
        # From: Appendix C (pp. 137) in Holt, G. R. A critical reexamination of
        # some assumptions and implications of cable theory in neurobiology.
        # CalTech, PhD Thesis (1998).
        #
        #                      Electrode position
        #   |------ L --------*
        #                 b / | R
        #                 /   |
        #   0==== a ====1- H -+
        #
        # a: vector oriented along the section
        # b: position vector of electrode with respect to section end (1)
        # H: parallel distance from section end to electrode
        # R: radial distance from section end to electrode
        # L: parallel distance from section start to electrode
        # Note that there are three distinct regimes to this approximation,
        # depending on the electrode position along the section axis.
        phi = np.zeros(len(seg_ctr))
        for idx, (ctr, line_len) in enumerate(zip(seg_ctr, line_lens)):
            start = ctr - line_len * sec_vec / norm(sec_vec)
            end = ctr + line_len * sec_vec / norm(sec_vec)
            a = end - start
            norm_a = norm(a)
            b = electrode_pos - end
            # projection: H = a.cos(theta) = a.dot(b) / |a|
            H = np.dot(b, a) / norm_a  # NB can be negative
            L = H + norm_a
            R2 = np.dot(b, b) - H ** 2  # NB squares

            # To avoid very large values when electrode is placed (anywhere) on
            # the section axis, enforce minimal perpendicular distance
            R2 = np.maximum(R2, min_distance ** 2)

            if L < 0 and H < 0:  # electrode is "behind" line segment
                num = np.sqrt(H ** 2 + R2) - H  # == norm(b) - H
                denom = np.sqrt(L ** 2 + R2) - L
            elif L > 0 and H < 0:  # electrode is "on top of" line segment
                num = (np.sqrt(H ** 2 + R2) - H) * (L + np.sqrt(L ** 2 + R2))
                denom = R2
            else:  # electrode is "ahead of" line segment
                num = np.sqrt(L ** 2 + R2) + L
                denom = np.sqrt(H ** 2 + R2) + H  # == norm(b) + H

            phi[idx] = np.log(num / denom) / norm_a

    # [dis]: um; [sigma]: S / m
    # [phi / sigma] = [1/dis] / [sigma] = 1 / [dis] x [sigma]
    # [dis] x [sigma] = um x (S / m) = 1e-6 S
    # transmembrane current returned by _ref_i_membrane_ is in [nA]
    # ==> 1e-9 A x (1 / 1e-6 S) = 1e-3 V = mV
    # ===> multiply by 1e3 to get uV
    return 1000.0 * phi / (4.0 * np.pi * sigma)


class ExtracellularArray:
    """Class for recording extracellular potential fields with electrode array

    Note that to add an electrode array to a simulation, you should use the
    :meth:`hnn_core.Network.add_electrode_array`-method. After simulation,
    the network will contain a dictionary of `ExtracellularArray`-objects
    in ``net.rec_array`` (each array must be added with a unique name). An
    `ExtracellularArray` contains the voltages at each electrode contact,
    along with the time points at which the voltages were sampled.

    Parameters
    ----------
    positions : tuple | list of tuple
        The (x, y, z) coordinates (in um) of the extracellular electrodes.
    sigma : float
        Extracellular conductivity, in S/m, of the assumed infinite,
        homogeneous volume conductor that the cell and electrode are in.
    method : str
        Approximation to use. ``'psa'`` (point source approximation) treats
        each segment junction as a point extracellular current source.
        ``'lsa'`` (line source approximation) treats each segment as a line
        source of current, which extends from the previous to the next segment
        center point: |---x---|, where x is the current segment flanked by |.
    min_distance : float (default: 0.5; unit: um)
        To avoid numerical errors in calculating potentials, apply a minimum
        distance limit between the electrode contacts and the active neuronal
        membrane elements that act as sources of current. The default value of
        0.5 um corresponds to 1 um diameter dendrites.
    times : None | list of float
        Optionally, provide precomputed voltage sampling times for electrodes
        at `positions`.
    voltages : None | list of list of list of float (3D)
        Optionally, provide precomputed voltages for electrodes at
        ``positions``. Note that the size of `voltages` must be:
        ``(n_trials, n_electrodes, n_times)``, i.e., three-dimensional.

    Attributes
    ----------
    times : list of float
        The time points the extracellular voltages are sampled at (ms)
    voltages : list of list of list of float
        A three-dimensional list with dimensions: (n_trials, n_electrodes,
        n_times).
    sfreq : float
        Sampling rate of the extracellular data (Hz).

    Notes
    -----
    See Table 5 in http://jn.physiology.org/content/104/6/3388.long for
    measured values of sigma in rat cortex (note units there are mS/cm)
    """

    def __init__(self, positions, *, sigma=0.3, method='psa',
                 min_distance=0.5, times=None, voltages=None):

        _validate_type(positions, (tuple, list), 'positions')
        if len(positions) == 3:  # a single coordinate given
            positions = [positions]
        for pos in positions:
            _validate_type(pos, (tuple, list), 'positions')
            if len(pos) != 3:
                raise ValueError('positions should be provided as xyz '
                                 f'coordinate triplets, got: {positions}')

        _validate_type(sigma, float, 'sigma')
        assert sigma > 0.0
        _validate_type(min_distance, float, 'min_distance')
        assert min_distance > 0.0
        try:  # allow None, but for testing only
            _validate_type(method, str, 'method')
            _check_option('method', method, ['psa', 'lsa'])
        except (TypeError, ValueError) as e:
            if method is None:
                pass
            else:
                raise e

        if times is None:
            times = list()
        if voltages is None:
            voltages = list()

        _validate_type(times, list, 'times')
        _validate_type(voltages, list, 'voltages')
        for ii in range(len(voltages)):
            if len(voltages[ii]) != len(positions):
                raise ValueError(f'number of voltage traces must match number'
                                 f' of channels, got {len(voltages[ii])} and '
                                 f'{len(positions)} for trial {ii}')
            for jj in range(len(voltages[ii])):
                if len(times) != len(voltages[ii][jj]):
                    raise ValueError('length of times and voltages must match,'
                                     f' got {len(times)} and '
                                     f'{len(voltages[ii][jj])} for trial{ii}, '
                                     f'channel {jj}')

        self.positions = positions
        self.n_contacts = len(self.positions)
        self.sigma = sigma
        self.method = method
        self.min_distance = min_distance

        self._times = times
        self._data = voltages

    def __getitem__(self, trial_no):
        try:
            if isinstance(trial_no, int):
                return_data = [self._data[trial_no]]
            elif isinstance(trial_no, slice):
                return_data = self._data[trial_no]
            elif isinstance(trial_no, (list, tuple)):
                return_data = [self._data[trial] for trial in trial_no]
            else:
                raise TypeError(f'trial index must be int, slice or list-like,'
                                f' got: {trial_no} which is {type(trial_no)}')
        except IndexError:
            raise IndexError(f'the data contain {len(self)} trials, the '
                             f'indices provided are out of range: {trial_no}')
        return ExtracellularArray(self.positions, sigma=self.sigma,
                                  method=self.method, times=self.times,
                                  voltages=return_data)

    def __repr__(self):
        class_name = self.__class__.__name__
        msg = (f'{self.n_contacts} electrodes, sigma={self.sigma}, '
               f'method={self.method}')
        if len(self._data) > 0:
            msg += f' | {len(self._data)} trials, {len(self.times)} times'
        else:
            msg += ' (no data recorded yet)'
        return f'<{class_name} | {msg}>'

    def __len__(self):
        return len(self._data)  # length == number of trials

    def copy(self):
        """Return a copy of the ExtracellularArray instance

        Returns
        -------
        array_copy : instance of ExtracellularArray
            A copy of the array instance.
        """
        return deepcopy(self)

    @property
    def times(self):
        return self._times

    @property
    def voltages(self):
        return self._data

    @property
    def sfreq(self):
        """Return the sampling rate of the extracellular data."""
        if len(self.times) == 0:
            return None
        elif len(self.times) == 1:
            raise RuntimeError('Sampling rate is not defined for one sample')

        dT = np.diff(self.times)
        Tsamp = np.median(dT)
        if np.abs(dT.max() - Tsamp) > 1e-3 or np.abs(dT.min() - Tsamp) > 1e-3:
            raise RuntimeError(
                'Extracellular sampling times vary by more than 1 us. Check '
                'times-attribute for errors.')

        return 1000. / Tsamp  # times are in in ms

    def _reset(self):
        self._data = list()
        self._times = list()

    def get_data(self, return_times=False):
        """Get extracellular electrode voltages as a Numpy array

        The data are returned as as a Numpy array with exactly 3 dimensions:
        (n_trials, n_channels, n_times), where ``n_channels`` are in the same
        order as defined in the positions-argument.

        Parameters
        ----------
        return_times : bool (default: False)
            If True, also return the sample times.

        Returns
        -------
        data : np.ndarray of shape (n_trials, n_channels, n_times)
            The electrode voltages
        times : np.ndarray of shape (n_times, )
            The sampling times
        """
        if return_times:
            return np.array(self._data), np.array(self._times)
        else:
            return np.array(self._data)

    def smooth(self, window_len):
        """Smooth extracellular waveforms using Hamming-windowed convolution

        Note that this method operates in-place, i.e., it will alter the data.
        If you prefer a filtered copy, consider using the
        :meth:`~hnn_core.extracellular.ExtracellularArray.copy`-method.

        Parameters
        ----------
        window_len : float
            The length (in ms) of a `~numpy.hamming` window to convolve the
            data with.

        Returns
        -------
        dpl_copy : instance of Dipole
            The modified Dipole instance.
        """
        from .utils import smooth_waveform

        for n_trial in range(len(self)):
            for n_contact in range(self.n_contacts):
                self._data[n_trial][n_contact] = smooth_waveform(
                    self._data[n_trial][n_contact], window_len,
                    self.sfreq).tolist()  # XXX smooth_waveform returns ndarray

        return self

    def plot(self, *, trial_no=None, contact_no=None, tmin=None, tmax=None,
             ax=None, decim=None, color=None, voltage_offset=None,
             voltage_scalebar=None, contact_labels=None, show=True):
        """Plot extracellular electrode array voltage time series.

        One plot is created for each trial. Multiple trials can be overlaid
        with or without (default) and offset.

        Parameters
        ----------
        trial_no : int | list of int | slice
            Trial number(s) to plot
        contact_no : int | list of int | slice
            Electrode contact number(s) to plot
        tmin : float | None
            Start time of plot in milliseconds. If None, plot entire
            simulation.
        tmax : float | None
            End time of plot in milliseconds. If None, plot entire simulation.
        ax : instance of matplotlib figure | None
            The matplotlib axis
        decim : int | list of int | None (default)
            Optional (integer) factor by which to decimate the raw dipole
            traces. The SciPy function :func:`~scipy.signal.decimate` is used,
            which recommends values <13. To achieve higher decimation factors,
            a list of ints can be provided. These are applied successively.
        color : string | array of floats | matplotlib.colors.ListedColormap
            The color to use for plotting (optional). The usual Matplotlib
            standard color strings may be used (e.g., 'b' for blue). A color
            can also be defined as an RGBA-quadruplet, or an array of
            RGBA-values (one for each electrode contact trace to plot). An
            instance of :class:`~matplotlib.colors.ListedColormap` may also be
            provided.
        voltage_offset : float | None (optional)
            Amount to offset traces by on the voltage-axis. Useful for plotting
            laminar arrays.
        voltage_scalebar : float | None (optional)
            Height, in units of uV, of a scale bar to plot in the top-left
            corner of the plot.
        contact_labels : list (optional)
            Labels associated with the contacts to plot. Passed as-is to
            :meth:`~matplotlib.axes.Axes.set_yticklabels`.
        show : bool
            If True, show the figure

        Returns
        -------
        fig : instance of plt.fig
            The matplotlib figure handle into which time series were plotted.
        """
        from .viz import plot_extracellular

        if trial_no is None:
            plot_data = self.get_data()
        elif isinstance(trial_no, (list, tuple, int, slice)):
            plot_data = self.get_data()[trial_no, ]
        else:
            raise ValueError(f'unkown trial number type, got {trial_no}')

        if isinstance(contact_no, (list, tuple, int, slice)):
            plot_data = plot_data[:, contact_no, ]
        elif contact_no is not None:
            raise ValueError(f'unkown contact number type, got {contact_no}')

        for trial_data in plot_data:
            fig = plot_extracellular(
                self.times, trial_data, tmin=tmin, tmax=tmax, ax=ax,
                decim=decim, color=color,
                voltage_offset=voltage_offset,
                voltage_scalebar=voltage_scalebar,
                contact_labels=contact_labels,
                show=show)
        return fig


class ExtracellularArrayBuilder(object):
    """The ExtracellularArrayBuilder class

    Parameters
    ----------
    array : ExtracellularArray object
        The instance of :class:`hnn_core.extracellular.ExtracellularArray` to
        build in NEURON-Python
    """
    def __init__(self, array):
        self.array = array
        self.n_contacts = array.n_contacts
        self._nrn_imem_ptrvec = None
        self._nrn_imem_vec = None
        self._nrn_r_transfer = None
        self._nrn_times = None
        self._nrn_voltages = None

    def _build(self, cvode=None):
        """Assemble NEURON objects for calculating extracellular potentials.

        The handler is set up to maintain a vector of membrane currents at at
        every inner segment of every section of every cell on each CVODE
        integration step. In addition, it records a time vector of sample
        times.

        Parameters
        ----------
        cvode : instance of h.CVode
            Multi order variable time step integration method.
        """
        # ordered list of h.Sections on this rank (if running in parallel)
        secs_on_rank = _get_sections_on_this_rank()
        # np.array of number of segments for each section, ordered as above
        segment_counts = np.array(_get_segment_counts(secs_on_rank))
        n_total_segments = segment_counts.sum()

        # pointers assigned to _ref_i_membrane_ at each EACH internal segment
        self._nrn_imem_ptrvec = h.PtrVector(n_total_segments)
        # placeholder into which pointer values are read on each sim time step
        self._nrn_imem_vec = h.Vector(n_total_segments)

        ptr_count = 0
        for sec in secs_on_rank:
            for seg in sec:  # section end points (0, 1) not included
                # set Nth pointer to the net membrane current at this segment
                self._nrn_imem_ptrvec.pset(
                    ptr_count, sec(seg.x)._ref_i_membrane_)
                ptr_count += 1
        if ptr_count != n_total_segments:
            raise RuntimeError(f'Expected {n_total_segments} imem pointers, '
                               f'got {ptr_count}.')

        # transfer resistances for each segment (keep in Neuron Matrix object)
        self._nrn_r_transfer = h.Matrix(self.n_contacts, n_total_segments)

        for row, pos in enumerate(self.array.positions):
            if self.array.method is not None:
                transfer_resistance = list()
                for sec in secs_on_rank:
                    this_xfer_r = _transfer_resistance(
                        sec, pos, sigma=self.array.sigma,
                        method=self.array.method,
                        min_distance=self.array.min_distance)
                    transfer_resistance.extend(this_xfer_r)

                self._nrn_r_transfer.setrow(row, h.Vector(transfer_resistance))
            else:
                # for testing, make a matrix of ones
                self._nrn_r_transfer.setrow(row,
                                            h.Vector(segment_counts.sum(), 1.))

        # record time for each array
        self._nrn_times = h.Vector().record(h._ref_t)

        # contributions of all segments on this rank to total calculated
        # potential at electrode (_PC.allreduce called in _simulate_dipole)
        self._nrn_voltages = h.Vector()
        self._nrn_imem_vec = h.Vector(n_total_segments)

        # Attach a callback for calculating the potentials at each time step.
        # Enables fast calculation of transmembrane current (nA) at each
        # segment. Note that this will run on each rank, so it is safe to use
        # the extra_scatter_gather-method, which docs say doesn't support
        # "multiple threads".
        cvode.extra_scatter_gather(0, self._calc_potentials_callback)

    @property
    def _nrn_n_samples(self):
        """Return the length (in samples) of the extracellular data."""
        if self._nrn_voltages.size() % self.n_contacts != 0:
            raise RuntimeError('Something went wrong: have {self.n_contacts}'
                               f', but {self._nrn_voltages.size()} samples')
        return int(self._nrn_voltages.size() / self.n_contacts)

    def _get_nrn_voltages(self):
        """The extracellular data (n_contacts x n_samples)."""
        if len(self._nrn_voltages) > 0:
            assert (self._nrn_voltages.size() ==
                    self.n_contacts * self._nrn_n_samples)

            # first reshape to a Neuron Matrix object
            extmat = h.Matrix(self.n_contacts, self._nrn_n_samples)
            extmat.from_vector(self._nrn_voltages)

            # then unpack into 2D python list and return
            return [extmat.getrow(ii).to_python() for
                    ii in range(extmat.nrow())]
        else:
            raise RuntimeError('Simulation not yet run!')

    def _get_nrn_times(self):
        """The sampling time points."""
        if self._nrn_times.size() > 0:
            # NB _nrn_times is one sample longer than _nrn_voltages
            return self._nrn_times.to_python()[:self._nrn_n_samples]
        else:
            raise RuntimeError('Simulation not yet run!')

    def _calc_potentials_callback(self):
        # keep all data in Neuron objects for efficiency

        # 'gather' the values of seg.i_membrane_ into self.imem_vec
        self._nrn_imem_ptrvec.gather(self._nrn_imem_vec)

        # Calculate potentials by multiplying the _nrn_imem_vec by the matrix
        # _nrn_r_transfer. This is equivalent to a row-by-row dot-product:
        # V_i = SUM_j (R_i,j x I_j)
        self._nrn_voltages.append(
            self._nrn_r_transfer.mulv(self._nrn_imem_vec))
        # NB all values appended to the h.Vector _nrn_voltages at current time
        # step. The vector will have sixe (n_contacts x n_samples, 1), which
        # will be reshaped later to (n_contacts, n_samples).