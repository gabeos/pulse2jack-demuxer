#!/usr/bin/env python3.5

import os,sys,logging
import argparse
from pulsectl import Pulse#, PulseLoopStop
from pulsectl._pulsectl import pa as libpulse
from time import sleep
import itertools
import math

class NoJackException(Exception):
    pass

class NoInputsException(Exception):
    pass

class PA2JACK(object):
    jacksink_channel_map = ['aux{}'.format(i) for i in range(16)]
    default_channel_map = ['front-left', 'front-right', 'rear-left' 'rear-right', 'lfe', 'subwoofer', 'side-left', 'side-right']

    def __init__(self,args):

        # get arguments
        if 'allow_reload' in args:
            self.allow_reload = args.allow_reload
        else: self.allow_reload = False
        self.restart = args.internal_restart
        self.num_channels = args.num_channels
        self.pulse_mon = Pulse('pa2jack-monitor') 
        self.pulse_act = Pulse('pa2jack-actor')

        # Get jack sink
        self.jack_sink = self._get_jack_sink()

        # Reload jack module with correct channels
        self.reload_jack_module(self.num_channels)

        # Unload module-remap-sink
        for m in self.pulse_act.module_list():
            if m.name == "module-remap-sink":
                self.pulse_act.module_unload(m.index) 

        # Make our stereo remapping sinks
        self.remap_sink_modules = set([self._new_remap_sink("remap_sink_{}".format(i),start=i*2) for i in range(math.floor(self.num_channels/2))])

        # Get sink indices
        self.remap_sinks = [s.index for s in self.pulse_act.sink_list() if s.owner_module in self.remap_sink_modules]

        # Listen to sink_input events and set handler
        self.pulse_mon.event_mask_set('sink_input')
        self.pulse_mon.event_callback_set(self._pa_event_handler)

    def _get_jack_sink(self):
        try:
            return next(s for s in self.pulse_act.sink_list() if s.name == 'jack_out')
        except StopIteration:
            logging.warn("Couldn't find jack_out sink.")
            return None

    def _default_channel_map(self,n_channels=2,start=0):
        return ",".join(self.default_channel_map[start:start+n_channels])

    def _jack_channel_map(self,start=0,n_channels=2):
        return ",".join(self.jacksink_channel_map[start:start+n_channels])

    def _new_remap_sink(self, sink_name, start=0,n_channels=2):
        logging.debug("making remap-sink: {} ({})".format(sink_name,n_channels))
        default_ch = self._default_channel_map(n_channels)
        aux_channels = self._jack_channel_map(start,n_channels)
        logging.debug("\naux_ch: {}\ndefault_ch: {}".format(aux_channels,default_ch))
        remap_index = self.pulse_act.module_load("module-remap-sink",
                               "sink_name={} master={} channel_map={} master_channel_map={} remix=no".format(
                                            str(sink_name), "jack_out",
                                            default_ch,
                                            aux_channels))
        logging.debug("Done loading module-remap-sink, ind: {}".format(remap_index))
        return remap_index

    def reload_jack_module(self,channels=2,channel_map=jacksink_channel_map):
        """Unload and reload 'module-jack-sink' with specified number of channels.

        Used to dynamically increase the number of available channels if the initial JACK sink cannot accommodate the number of PA streams.
        Will cause a small stutter in the audio, so only enable if that's okay with your environment."""

        #TODO: Insert check for module-default-device-restore // module-rescue-streams before reloading
        try:
            self.pulse_act.module_unload(self.jack_sink.owner_module)
        except:
            logging.warn("Couldn't unload jack module to restart")
        try:
            self.pulse_act.module_load("module-jack-sink","channels={} channel_map={}".format(channels,",".join(channel_map[:channels])))
            self.jack_sink = self._get_jack_sink()
        except:
            logging.warn("Couldn't load JACK module")
            raise NoJackException()

    def _get_dirty_remap_sinks(self):
        return set(map(lambda si: si.sink, self.pulse_act.sink_input_list()))

    def _handle_new_input(self,pa_event):
        # Load remap source module
        logging.debug("New Input: {}".format(pa_event))
        dirty_sinks = self._get_dirty_remap_sinks()
        logging.debug("dirty_sinks: {}".format(dirty_sinks))
        for si in self.remap_sinks:
            if si not in dirty_sinks:
                logging.debug("Moving input {} to sink {}".format(pa_event.index, si))
                self.pulse_act.sink_input_move(pa_event.index,si)
                return

    def _pa_event_handler(self,pa_event):
        """Monitor and distribute Pulseaudio Events.
        """
        logging.debug("Event received: {}".format(pa_event))
        if pa_event.t == 'new' and pa_event.facility == 'source_output':
            self._handle_new_source(pa_event)
        elif pa_event.t == 'new' and pa_event.facility == 'sink_input':
            self._handle_new_input(pa_event)

    def run(self,reloading=False,log=sys.stdout,restart=False):
        """Hacky process monitor catches all exceptions and restarts process if it fails.

        Really you should use a real process monitor, like supervisord or monit."""
        if restart:
            while True:
                try:
                    self.pulse_mon.event_listen()
                except Exception as err:
                    logging.warn("Exception raised in run loop: ".format(err))
                    continue
        else:
            self.pulse_mon.event_listen()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--allow-reloading", help="Allow reloading jack module connection to increase channels. Warning: Reloading will result in audio dropouts.")
    parser.add_argument("--log",help="File to log output")
    parser.add_argument("--loglevel",help="Log Level",default="debug")
    parser.add_argument("--internal-restart",help="Hacky way to ensure this stays running")
    parser.add_argument("-c", "--num-channels", help="Number of channels to connect to JACK", default=12)
    parser.add_help

    loglevels = {
        "debug": logging.DEBUG,
        "warn": logging.WARN,
        "info": logging.INFO,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
        "fatal": logging.FATAL
    }
    args = parser.parse_args()
    loglevel = loglevels.get(args.loglevel)
    if loglevel is None:
        loglevel = loglevel if loglevel is not None else logging.DEBUG
        logging.warn("Log level {} not recognized. Defaulting to DEBUG.".format(args.loglevel))

    if args.log:
        logging.basicConfig(filename=args.log,level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.DEBUG)
    p2j = PA2JACK(args)
    p2j.run()
