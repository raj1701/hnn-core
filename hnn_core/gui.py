"""IPywidgets GUI."""

# Authors: Mainak Jas <mjas@mgh.harvard.edu>
#          Huzi Cheng <hzcheng15@icloud.com>

import codecs
import os.path as op
import subprocess

import matplotlib.pyplot as plt
import numpy as np
from IPython.display import display
from ipywidgets import (HTML, Accordion, AppLayout, BoundedFloatText, Button,
                        Dropdown, FileUpload, FloatLogSlider, FloatText, Text,
                        HBox, IntText, Layout, Output, RadioButtons, Tab, VBox,
                        interactive, interactive_output)

import hnn_core
from hnn_core import Network, read_params, simulate_dipole, MPIBackend
from hnn_core.params import _read_json, _read_legacy_params
import multiprocessing


def cmd_exists(cmd):
    return subprocess.call("type " + cmd,
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE) == 0


def create_expanded_button(description, button_style, height):
    style = {'button_color': '#8A2BE2'}
    return Button(description=description,
                  button_style=button_style,
                  layout=Layout(height=height, width='auto'),
                  style=style)


def _get_sliders(params, param_keys):
    """Get sliders"""
    style = {'description_width': '150px'}
    sliders = list()
    for d in param_keys:
        slider = FloatLogSlider(value=params[d],
                                min=-5,
                                max=1,
                                step=0.2,
                                description=d.split('gbar_')[1],
                                disabled=False,
                                continuous_update=False,
                                orientation='horizontal',
                                readout=True,
                                readout_format='.2e',
                                style=style)
        sliders.append(slider)

    def _update_params(variables, **updates):
        params.update(dict(**updates))

    interactive_output(_update_params, {s.description: s for s in sliders})
    return sliders


def _get_cell_specific_widgets(layout, style, location):
    kwargs = dict(layout=layout, style=style)
    cell_types = ['L5_pyramidal', 'L2_pyramidal', 'L5_basket', 'L2_basket']
    if location == "distal":
        cell_types.remove('L5_basket')

    weights_ampa, weights_nmda, delays = dict(), dict(), dict()
    for cell_type in cell_types:
        weights_ampa[f'{cell_type}'] = FloatText(value=0.,
                                                 description=f'{cell_type}:',
                                                 **kwargs)
        weights_nmda[f'{cell_type}'] = FloatText(value=0.,
                                                 description=f'{cell_type}:',
                                                 **kwargs)
        delays[f'{cell_type}'] = FloatText(value=0.1,
                                           description=f'{cell_type}:',
                                           **kwargs)

    widgets_dict = {
        'weights_ampa': weights_ampa,
        'weights_nmda': weights_nmda,
        'delays': delays
    }
    widgets_list = ([HTML(value="<b>AMPA weights</b>")] +
                    list(weights_ampa.values()) +
                    [HTML(value="<b>NMDA weights</b>")] +
                    list(weights_nmda.values()) +
                    [HTML(value="<b>Synaptic delays</b>")] +
                    list(delays.values()))
    return widgets_list, widgets_dict


def _get_rhythmic_widget(name, tstop_widget, layout, style, location):

    kwargs = dict(layout=layout, style=style)
    tstart = FloatText(value=0., description='Start time (s)', **kwargs)
    tstart_std = FloatText(value=0, description='Start time dev (s)', **kwargs)
    tstop = BoundedFloatText(value=tstop_widget.value,
                             description='Stop time (s)',
                             max=tstop_widget.value,
                             **kwargs)
    burst_rate = FloatText(value=7.5, description='Burst rate (Hz)', **kwargs)
    burst_std = FloatText(value=0, description='Burst std dev (Hz)', **kwargs)
    repeats = FloatText(value=1, description='Repeats', **kwargs)
    seedcore = IntText(value=14, description='Seed', **kwargs)

    widgets_list, widgets_dict = _get_cell_specific_widgets(
        layout, style, location)
    drive_box = VBox(
        [tstart, tstart_std, tstop, burst_rate, burst_std, repeats, seedcore] +
        widgets_list)
    drive = dict(type='Rhythmic',
                 name=name,
                 tstart=tstart,
                 tstart_std=tstart_std,
                 burst_rate=burst_rate,
                 burst_std=burst_std,
                 repeats=repeats,
                 seedcore=seedcore,
                 tstop=tstop)
    drive.update(widgets_dict)
    return drive, drive_box


def _get_poisson_widget(name, tstop_widget, layout, style, location):
    tstart = FloatText(value=0.0,
                       description='Start time (s)',
                       layout=layout,
                       style=style)
    tstop = BoundedFloatText(value=tstop_widget.value,
                             max=tstop_widget.value,
                             description='Stop time (s)',
                             layout=layout,
                             style=style)
    seedcore = IntText(value=14,
                       description='Seed',
                       layout=layout,
                       style=style)
    location = RadioButtons(options=['proximal', 'distal'])

    cell_types = ['L5_pyramidal', 'L2_pyramidal', 'L5_basket', 'L2_basket']
    rate_constant = dict()
    for cell_type in cell_types:
        rate_constant[f'{cell_type}'] = FloatText(value=8.5,
                                                  description=f'{cell_type}:',
                                                  layout=layout,
                                                  style=style)

    widgets_list, widgets_dict = _get_cell_specific_widgets(
        layout, style, location)
    widgets_dict.update({'rate_constant': rate_constant})
    widgets_list.extend([HTML(value="<b>Rate constants</b>")] +
                        list(widgets_dict['rate_constant'].values()))

    drive_box = VBox([tstart, tstop, seedcore] + widgets_list)
    drive = dict(
        type='Poisson',
        name=name,
        tstart=tstart,
        tstop=tstop,
        rate_constant=rate_constant,
        seedcore=seedcore,
    )
    drive.update(widgets_dict)
    return drive, drive_box


def _get_evoked_widget(name, layout, style, location):
    kwargs = dict(layout=layout, style=style)
    mu = FloatText(value=0, description='Mean time:', **kwargs)
    sigma = FloatText(value=1, description='Std dev time:', **kwargs)
    numspikes = IntText(value=1, description='No. Spikes:', **kwargs)
    seedcore = IntText(value=14, description='Seed: ', **kwargs)

    widgets_list, widgets_dict = _get_cell_specific_widgets(
        layout, style, location)

    drive_box = VBox([mu, sigma, numspikes, seedcore] + widgets_list)
    drive = dict(type='Evoked',
                 name=name,
                 mu=mu,
                 sigma=sigma,
                 numspikes=numspikes,
                 seedcore=seedcore,
                 sync_within_trial=False)
    drive.update(widgets_dict)
    return drive, drive_box


def add_drive_widget(drive_type, drive_boxes, drive_widgets, drives_out,
                     tstop_widget, location):
    """Add a widget for a new drive."""
    layout = Layout(width='270px', height='auto')
    style = {'description_width': '150px'}
    drives_out.clear_output()
    with drives_out:
        name = drive_type + str(len(drive_boxes))

        if drive_type == 'Rhythmic':
            drive, drive_box = _get_rhythmic_widget(name, tstop_widget, layout,
                                                    style, location)
        elif drive_type == 'Poisson':
            drive, drive_box = _get_poisson_widget(name, tstop_widget, layout,
                                                   style, location)
        elif drive_type == 'Evoked':
            drive, drive_box = _get_evoked_widget(name, layout, style,
                                                  location)

        if drive_type in ['Evoked', 'Poisson', 'Rhythmic']:
            drive_boxes.append(drive_box)
            drive_widgets.append(drive)

        accordion = Accordion(children=drive_boxes,
                              selected_index=len(drive_boxes) - 1)
        for idx, drive in enumerate(drive_widgets):
            accordion.set_title(idx, drive['name'])
        display(accordion)


def update_plot_window(variables, _plot_out, plot_type):
    # TODO need to add more informaion about "no data"
    _plot_out.clear_output()

    if not (plot_type['type'] == 'change' and plot_type['name'] == 'value'):
        return

    with _plot_out:
        fig, ax = plt.subplots()

        if plot_type['new'] == 'spikes':
            if variables['net'] is not None and sum(
                [len(_)
                 for _ in variables['net'].cell_response._spike_times]) > 0:
                variables['net'].cell_response.plot_spikes_raster(ax=ax)
            else:
                print("No data")

        elif plot_type['new'] == 'current dipole':
            if variables['dpls'] is not None:
                variables['dpls'][0].plot(ax=ax)
            else:
                print("No data")

        elif plot_type['new'] == 'input histogram':
            # BUG: got error here, need a better way to handle exception
            if variables['net'] is not None and sum(
                [len(_)
                 for _ in variables['net'].cell_response._spike_times]) > 0:
                variables['net'].cell_response.plot_spikes_hist(ax=ax)
            else:
                print("No data")

        elif plot_type['new'] == 'PSD':
            if variables['dpls'] is not None:
                variables['dpls'][0].plot_psd(fmin=0, fmax=50, ax=ax)
            else:
                print("No data")

        elif plot_type['new'] == 'spectogram':
            freqs = np.arange(10., 100., 1.)
            n_cycles = freqs / 8.
            if variables['dpls'] is not None:
                variables['dpls'][0].plot_tfr_morlet(freqs,
                                                     n_cycles=n_cycles,
                                                     ax=ax)
            else:
                print("No data")

        elif plot_type['new'] == 'network':
            if variables['net'] is not None:
                variables['net'].plot_cells(ax=ax)
            else:
                print("No data")


def on_upload_change(change, sliders, params, tstop, tstep, log_out):
    if len(change['owner'].value) == 0:
        return

    params_fname = change['owner'].metadata[0]['name']
    file_uploaded = change['owner'].value
    param_data = list(file_uploaded.values())[0]['content']
    param_data = codecs.decode(param_data, encoding="utf-8")

    ext = op.splitext(params_fname)[1]
    read_func = {'.json': _read_json, '.param': _read_legacy_params}
    params_network = read_func[ext](param_data)

    log_out.clear_output()
    with log_out:
        print(f"parameters: {params_network.keys()}")

    for slider in sliders:
        for sl in slider:
            key = 'gbar_' + sl.description
            sl.value = params_network[key]

    if 'tstop' in params_network.keys():
        tstop.value = params_network['tstop']
    if 'dt' in params_network.keys():
        tstep.value = params_network['dt']

    params.update(params_network)


def run_button_clicked(log_out, plot_out, drive_widgets, variables, tstep,
                       tstop, ntrials, mpi_cmd, params, b):
    """Run the simulation and plot outputs."""
    plot_out.clear_output()
    log_out.clear_output()
    with log_out:
        params['dt'] = tstep.value
        params['tstop'] = tstop.value
        variables['net'] = Network(params, add_drives_from_params=False)

    try:
        for drive in drive_widgets:
            weights_ampa = {
                k: v.value
                for k, v in drive['weights_ampa'].items()
            }
            weights_nmda = {
                k: v.value
                for k, v in drive['weights_nmda'].items()
            }
            synaptic_delays = {k: v.value for k, v in drive['delays'].items()}
            if drive['type'] == 'Poisson':
                rate_constant = {
                    k: v.value
                    for k, v in drive['rate_constant'].items() if v.value > 0
                }
                weights_ampa = {
                    k: v
                    for k, v in weights_ampa.items() if k in rate_constant
                }
                weights_nmda = {
                    k: v
                    for k, v in weights_nmda.items() if k in rate_constant
                }
                variables['net'].add_poisson_drive(
                    name=drive['name'],
                    tstart=drive['tstart'].value,
                    tstop=drive['tstop'].value,
                    rate_constant=rate_constant,
                    location=drive['location'].value,
                    weights_ampa=weights_ampa,
                    weights_nmda=weights_nmda,
                    synaptic_delays=synaptic_delays,
                    space_constant=100.0,
                    seedcore=drive['seedcore'].value)
            elif drive['type'] == 'Evoked':
                variables['net'].add_evoked_drive(
                    name=drive['name'],
                    mu=drive['mu'].value,
                    sigma=drive['sigma'].value,
                    numspikes=drive['numspikes'].value,
                    # sync_within_trial=False,
                    # BUG it seems this is something unnecessary
                    location=drive['location'].value,
                    weights_ampa=weights_ampa,
                    weights_nmda=weights_nmda,
                    synaptic_delays=synaptic_delays,
                    space_constant=3.0,
                    seedcore=drive['seedcore'].value)
            elif drive['type'] == 'Rhythmic':
                variables['net'].add_bursty_drive(
                    name=drive['name'],
                    tstart=drive['tstart'].value,
                    tstart_std=drive['tstart_std'].value,
                    burst_rate=drive['burst_rate'].value,
                    burst_std=drive['burst_std'].value,
                    # repeats=drive['repeats'].value, # BUG
                    location=drive['location'].value,
                    tstop=drive['tstop'].value,
                    weights_ampa=weights_ampa,
                    weights_nmda=weights_nmda,
                    synaptic_delays=synaptic_delays,
                    seedcore=drive['seedcore'].value)
    except Exception as e:
        with log_out:
            print(f"error in reading drives {e}")

    with log_out:
        log_out.clear_output()
        print("start simulation")
        if cmd_exists(mpi_cmd.value):
            # should further allow users to adjust cores to use
            # with MPIBackend(n_procs=multiprocessing.cpu_count() - 1,
            #                 mpi_cmd=mpi_cmd.value):
            # variables['dpls'] = simulate_dipole(variables['net'],
            #                                     tstop=tstop.value,
            #                                     n_trials=ntrials.value)
            variables['backend'] = MPIBackend(
                n_procs=multiprocessing.cpu_count() - 1, mpi_cmd=mpi_cmd.value)
            variables['dpls'] = variables['backend'].simulate(
                variables['net'],
                tstop.value,
                tstep.value,
                n_trials=ntrials.value)

        else:
            variables['dpls'] = simulate_dipole(variables['net'],
                                                tstop=tstop.value,
                                                n_trials=ntrials.value)

    # Default case
    with plot_out:
        fig, ax = plt.subplots()
        variables['dpls'][0].plot(ax=ax)


def stop_button_clicked(variables, log_out, b):
    # BUG: this cannot work properly now.
    with log_out:
        if "backend" in variables:
            print("Terminating simulation...")
            variables["backend"].terminate()
        else:
            print("No Backends or running simulations. Cannot terminate")


def test_del_widget(plot_out_1):
    del plot_out_1
    pass


def run_hnn_gui():
    """Create the HNN GUI."""

    hnn_core_root = op.join(op.dirname(hnn_core.__file__))

    params_fname = op.join(hnn_core_root, 'param', 'default.json')
    params = read_params(params_fname)

    drive_widgets = list()
    drive_boxes = list()
    variables = dict(net=None, dpls=None)

    def _run_button_clicked(b):
        return run_button_clicked(log_out, plot_out, drive_widgets, variables,
                                  tstep, tstop, ntrials, mpi_cmd, params, b)

    def _stop_button_clicked(b):
        return stop_button_clicked(variables, log_out, b)

    def _on_upload_change(change):
        return on_upload_change(change, sliders, params, tstop, tstep, log_out)
        # BUG: capture does not work, use log_out explicitly
        # return on_upload_change(change, sliders, params)

    def _update_plot_window(plot_type):
        return update_plot_window(variables, plot_out, plot_type)

    def _update_plot_window_1(plot_type):
        return update_plot_window(variables, plot_out_1, plot_type)

    def _delete_drives_clicked(b):
        drives_out.clear_output()
        # black magic: the following does not work
        # global drive_widgets; drive_widgets = list()
        while len(drive_widgets) > 0:
            drive_widgets.pop()
            drive_boxes.pop()

    def _debug_change(b):
        test_del_widget(plot_out_1)

        with log_out:
            log_out.clear_output()
            print("file uploaded")
        pass

    # Output windows
    drives_out = Output()  # window to add new drives
    log_out = Output(layout={
        'border': '1px solid gray',
        'height': '150px',
        'overflow_y': 'auto'
    })
    height_plot = '350px'
    plot_out = Output(layout={
        'border': '1px solid gray',
        'height': height_plot
    })
    plot_out_1 = Output(layout={
        'border': '1px solid gray',
        'height': height_plot
    })

    # header_button
    header_button = create_expanded_button('HUMAN NEOCORTICAL NEUROSOLVER',
                                           'success',
                                           height='40px')

    # Simulation parameters
    tstop = FloatText(value=170, description='tstop (s):', disabled=False)
    tstep = FloatText(value=0.025, description='tstep (s):', disabled=False)
    ntrials = IntText(value=1, description='Trials:', disabled=False)
    mpi_cmd = Text(value='mpiexec',
                   placeholder='Fill if applies',
                   description='MPI cmd:',
                   disabled=False)
    simulation_box = VBox([tstop, tstep, ntrials, mpi_cmd])

    # Sliders to change local-connectivity params
    sliders = [
        _get_sliders(params, [
            'gbar_L2Pyr_L2Pyr_ampa', 'gbar_L2Pyr_L2Pyr_nmda',
            'gbar_L2Basket_L2Pyr_gabaa', 'gbar_L2Basket_L2Pyr_gabab'
        ]),
        _get_sliders(params, [
            'gbar_L2Pyr_L5Pyr', 'gbar_L2Basket_L5Pyr', 'gbar_L5Pyr_L5Pyr_ampa',
            'gbar_L5Pyr_L5Pyr_nmda', 'gbar_L5Basket_L5Pyr_gabaa',
            'gbar_L5Basket_L5Pyr_gabab'
        ]),
        _get_sliders(params,
                     ['gbar_L2Pyr_L2Basket', 'gbar_L2Basket_L2Basket']),
        _get_sliders(params, ['gbar_L2Pyr_L5Pyr', 'gbar_L2Basket_L5Pyr'])
    ]

    # accordians to group local-connectivity by cell type
    boxes = [VBox(slider) for slider in sliders]
    titles = [
        'Layer 2/3 Pyramidal', 'Layer 5 Pyramidal', 'Layer 2 Basket',
        'Layer 5 Basket'
    ]
    accordian = Accordion(children=boxes)
    for idx, title in enumerate(titles):
        accordian.set_title(idx, title)

    # Dropdown for different drives
    layout = Layout(width='200px', height='100px')

    drive_type_selection = RadioButtons(
        options=['Evoked', 'Poisson', 'Rhythmic'],
        value='Evoked',
        description='Drive:',
        disabled=False,
        layout=layout)

    location_selection = RadioButtons(options=['proximal', 'distal'],
                                      value='proximal',
                                      description='Location',
                                      disabled=False,
                                      layout=layout)

    add_drive_button = create_expanded_button('Add drive',
                                              'primary',
                                              height='30px')

    def _add_drive_button_clicked(b):
        return add_drive_widget(drive_type_selection.value, drive_boxes,
                                drive_widgets, drives_out, tstop,
                                location_selection.value)

    add_drive_button.on_click(_add_drive_button_clicked)
    drive_selections = VBox(
        [HBox([drive_type_selection, location_selection]), add_drive_button])

    # XXX: should be simpler to use Stacked class starting
    # from IPywidgets > 8.0
    drives_options = VBox([drive_selections, drives_out])

    # Tabs for left pane
    left_tab = Tab()
    left_tab.children = [simulation_box, accordian, drives_options]
    titles = ['Simulation', 'Cell connectivity', 'Drives']
    for idx, title in enumerate(titles):
        left_tab.set_title(idx, title)

    # Dropdown menu to switch between plots
    plot_options = [
        'input histogram', 'current dipole', 'spikes', 'PSD', 'spectogram',
        'network'
    ]
    plot_dropdown = Dropdown(options=plot_options,
                             value='current dipole',
                             description='Plot:',
                             disabled=False)

    interactive(_update_plot_window, plot_type='current dipole')
    plot_dropdown.observe(_update_plot_window, 'value')

    plot_dropdown_1 = Dropdown(options=plot_options,
                               value='current dipole',
                               description='Plot:',
                               disabled=False)
    interactive(_update_plot_window_1, plot_type='current dipole')
    plot_dropdown_1.observe(_update_plot_window_1, 'value')

    # Run, delete drives and load button
    run_button = create_expanded_button('Run', 'success', height='30px')
    stop_button = create_expanded_button('Stop', 'danger', height='30px')
    style = {'button_color': '#8A2BE2', 'font_color': 'white'}
    load_button = FileUpload(accept='.json,.param',
                             multiple=False,
                             style=style,
                             description='Load network',
                             button_style='success')
    delete_button = create_expanded_button('Delete drives',
                                           'success',
                                           height='30px')
    debug_button = create_expanded_button('Debug', 'success', height='30px')

    debug_button.on_click(_debug_change)
    # load_button.observe(_debug_change)

    # run_button.on_click(_debug_change)
    load_button.observe(_on_upload_change)
    run_button.on_click(_run_button_clicked)
    # Not working currently
    stop_button.on_click(_stop_button_clicked)
    delete_button.on_click(_delete_drives_clicked)
    footer = HBox(
        [run_button, stop_button, load_button, delete_button, debug_button])

    plot_dropdown_1.layout.width = "500px"
    plot_out.layout.width = "500px"
    right_sidebar = VBox([
        HBox([
            VBox([plot_dropdown, plot_out]),
            VBox([plot_dropdown_1, plot_out_1])
        ]), log_out
    ])

    # Final layout of the app
    hnn_gui = AppLayout(header=header_button,
                        left_sidebar=left_tab,
                        right_sidebar=right_sidebar,
                        footer=footer,
                        pane_widths=['380px', '0px', '1000px'],
                        pane_heights=[1, '500px', 1])
    return hnn_gui