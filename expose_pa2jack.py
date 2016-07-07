#!/usr/bin/env python3

import os,sys,logging
import argparse
from pulsectl import Pulse#, PulseLoopStop
from pulsectl._pulsectl import pa as libpulse

class NoJackException(Exception):
    pass

class PA2JACK(object):
    
    default_channel_map = ['front-left', 'front-right', 'rear-left' 'rear-right', 'lfe', 'subwoofer', 'side-left', 'side-right']
    
    def __init__(self,args):
        if 'allow_reload' in args:
            self.allow_reload = args.allow_reload
        else: self.allow_reload = False
        logging.info("Allow Reload: {}".format(self.allow_reload))
        self.restart = args.internal_restart
        self.pulse_mon = Pulse('pa2jack-monitor') 
        self.pulse_act = Pulse('pa2jack-actor')
        try:
            self.jack_sink = self._get_jack_sink()
            self.num_jack_in = self.jack_sink.description
        except StopIteration:
            logging.error("Could not find 'jack_out' sink. Exiting.")
            raise NoJackException("No JACK sink found in Pulseaudio.")
        
        self.pulse_mon.event_mask_set('all')
        self.pulse_mon.event_callback_set(self._pa_event_handler)

        logging.debug('Event types: {}'.format(', '.join(self.pulse_mon.event_types)))
        logging.debug('Event facilities: {}'.format(', '.join(self.pulse_mon.event_facilities)))
        logging.debug('Event masks: {}'.format(', '.join(self.pulse_mon.event_masks)))
        logging.info("Jack Sink Info:")
        logging.info(getattr(self.jack_sink,'channel_count'))
        for atr in dir(self.jack_sink):
            logging.info("{}: {}".format(atr,getattr(self.jack_sink, atr)))
            
#         for atr in dir(self.pulse_mon):
#             logging.info("{}: {}".format(atr,getattr(self.pulse_mon, atr)))
            
            
    def _get_jack_sink(self):
        return next(s for s in self.pulse_act.sink_list() if s.name == 'jack_out')

    def _get_source_by_id(self,ind): 
        logging.debug("source_output_list: {}".format(self.pulse_act.source_output_list()))
        source_out = next(s for s in self.pulse_act.source_output_list() if s.index == ind)
        logging.debug(source_out)
        return source_out

    def _get_master_channel_map(self):
        logging.debug(self.pulse_act.sink_input_list())
        return "rear-left,rear-right"
    
    def _new_remap_sink(self,source_name,n_channels=2):
        logging.debug("Remapping Source to Jack Sink")
        logging.debug("Module Args: sourcename={} master={} channels={} channel_map={} master_channel_map={} remix=no".format(
                                            source_name, 'jack_sink', n_channels, 
                                            ",".join(self.default_channel_map[0:n_channels]), 
                                            self._get_master_channel_map()))
        self.pulse_act.load_module('module-remap-sink', 
                               "sourcename={} master={} channels={} channel_map={} master_channel_map={} remix=no".format(
                                            source_name, 'jack_sink', n_channels, 
                                            ",".join(self.default_channel_map[0:n_channels]), 
                                            self._get_master_channel_map()))
        logging.debug("Done loading module-remap-sink")
    
    def reload_jack_module(self,channels=2):
        """Unload and reload 'module-jack-sink' with specified number of channels.
        
        Used to dynamically increase the number of available channels if the initial JACK sink cannot accommodate the number of PA streams.
        Will cause a small stutter in the audio, so only enable if that's okay with your environment."""
        
        #TODO: Insert check for module-default-device-restore // module-rescue-streams before reloading
        try:
            self.pulse_act.unload_module(self.jack_sink.owner_module)
            self.pulse_act.load_module("module-jack-sink","channels={}".format(channels))
            self.jack_sink = self._get_jack_sink()    
        except:
            logging.warn("Couldn't unload jack module to restart")
            raise NoJackException()

    
    def _handle_new_source(self,pa_event):
        logging.debug("New Source Idx: {}".format(pa_event.index))
        logging.debug("dir(pa_event): {}".format(dir(pa_event)))
        logging.debug("PA_EVENT_INDEX: {}".format(pa_event.index))
        source = self._get_source_by_id(pa_event.index)
        logging.debug("SOURCE:".format(source))
        logging.debug("SOURC_NAME: {}".format(source.name))
        logging.debug("NEW Source Name: {}".format(source.name))

        # Load remap source module
        self._new_remap_sink(source.name)
        # Move source output to remap source
        
        
    def _pa_event_handler(self,pa_event):
        """Monitor and distribute Pulseaudio Events.
        """
        logging.debug(pa_event)
        if pa_event.t == 'new' and pa_event.facility == 'source_output':
            logging.debug(pa_event)
            self._handle_new_source(pa_event)
            
        # Set up events and callbacks
        
        # Each callback should connect a source map, and connect to jack sink.
        # Configure source map node with info from jack sink.
        
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
    parser.add_argument("--internal-restart",help="Hacky way to ensure this stays running")
    parser.add_help
    
    args = parser.parse_args()
    if args.log:
        logging.basicConfig(filename=args.log,level=logging.DEBUG)
    p2j = PA2JACK(args)
    p2j.run()
#     p2j.reload_jack_module()
    
    