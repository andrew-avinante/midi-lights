import argparse
from command import Command
from config import Config
import json
import logging
from mido import MidiFile
import os

used_notes = []

class Choreographer(object):

    def __init__(self, _config):
        """
        :param _config:
        :type _config: Config
        """
        self.config = _config

        # Set up host arrays for commands
        self.nodes = {}
        self.channel_nodes = {}
        self.measure_timestamps = []
        self.global_time = 0
        for node_id, node in config.settings['nodes'].items():
            self.nodes[node_id] = {
                'channels': node['channels'].keys(),
                'current_time': 0,
                'commands': [],
                'cmd': Command()
            }

            for channel_id, channel_data in node['channels'].items():
                self.channel_nodes[channel_id] = node_id

        logging.debug("Choreographer Set Up {}".format(self.toJson({'channel_nodes': self.channel_nodes})))

    def toJson(self, thing):
        return json.dumps(thing, indent=2, separators=(',', ': '), sort_keys=True)
    
    def get_bars_per_minute(self, song_config):
        return song_config['tempo'] / song_config['beatsPerBar']
    
    def get_seconds_per_bar(self, song_config):
        return 60 / self.get_bars_per_minute(song_config)
    
    def generate_measure_timestamps(self, song_config):
        seconds_per_bar = self.get_seconds_per_bar(song_config)
        for i in range(song_config["total_bars"]):
            self.measure_timestamps.append(i * seconds_per_bar)

    def get_current_bar_config(self, song_config):
        for i, v in enumerate(self.measure_timestamps):
            if self.global_time <= v:
                for j in song_config["measures"].keys():
                    if i - 1 in range(int(j.split('-')[0]), int(j.split('-')[1]) + 1):
                        return song_config["measures"][j]
                    
                return None
                    
        return None
            
    def midi_commands(self, song_config):
        """
        Reads a midi file and generates commands before playing music (I was noticing the lights getting out of sync,
        and computing the list of commands before starting music playback fixed that issue). It was also easy to write
        the list out to a JSON file for caching on subsequent executions.

        :param song_config:
        :type song_config: dict

        :return: (cache_found, Command[])
        """
        total_time = 0

        midi_path = './music/{}'.format(song_config['midi'])
        commands_path = './music/{}'.format(song_config['commands'])

        logging.info("Building commands for midi: {}".format(midi_path))

        self.generate_measure_timestamps(song_config)

        # Parse midi file and generate commands
        for msg in MidiFile(midi_path):
            if msg.is_meta:
                continue
            if str(msg.type) not in ['note_on', 'note_off']:
                continue

            # If time, rotate all commands
            if msg.time:
                total_time += msg.time
                for node_name, node in self.nodes.items():
                    # If no changes with the current command, just increase timeout
                    if len(node['cmd'].changes) == 0:
                        node['cmd'].increase_timeout(msg.time)
                    # If commands staged, append to list and stage a new command
                    else:
                        node['commands'].append(node['cmd'])
                        node['cmd'] = Command(msg.time)


            self.global_time += msg.time
            measure_config = self.get_current_bar_config(song_config)

            if measure_config is None or msg.channel not in measure_config['channels']:
                continue

            # Get data from midi
            note_enabled = 1 if str(msg.type) == str('note_on') else 0
            note = self.midi_to_note(msg.note)

            if note not in used_notes:
                used_notes.append(note)

            if note not in measure_config['note_channel_map']:
                continue

            channel_ids = measure_config['note_channel_map'][note]

            # Debug log
            logging.debug("MIDI: {}".format(json.dumps({'note': note, 'on': note_enabled, 'channel_ids': channel_ids})))

            for ch_id in channel_ids:
                node_id = self.channel_nodes[ch_id]
                logging.debug("[{node}] {channel} {state}".format(node=node_id, channel=ch_id,
                                                                  state=("on" if note_enabled else "off")))

                self.nodes[node_id]['cmd'].set_channel(ch_id, note_enabled)

        # Write commands to file for caching
        for node_name, node in self.nodes.items():
            logging.info("Writing cache for [{node}]".format(node=node_name))
            cache_file_path = commands_path.format(node=node_name)

            # Bust cache
            if os.path.exists(cache_file_path):
                logging.info("Removed old cache file: {}".format(cache_file_path))
                os.remove(cache_file_path)

            # Write cache
            with open(cache_file_path, 'w') as cache_file:
                # Add last command if set
                if node['cmd'] is not None and len(node['cmd'].changes) > 0:
                    node['commands'].append(node['cmd'])
                    node['cmd'] = None

                # Write to file
                json.dump([cmd.__dict__ for cmd in node['commands']], cache_file,
                          indent=2, separators=(',', ': '), sort_keys=True)

    @staticmethod
    def midi_to_note(midi_number):
        num_c3 = midi_number - (81 - 4 * 12 - 9)
        note = (num_c3 + .5) % 12 - .5

        names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        octave = str(int(round((num_c3 - note) / 12.)))

        return names[int(round(note))] + octave


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    config = Config()

    parser.add_argument('--song', required=True, help='Song key from config.json to prepare')
    parser.add_argument('--loglevel', default='INFO', help='Log level. Defaults to INFO')

    args = parser.parse_args()

    logging.basicConfig(
        level=args.loglevel,
        format='%(asctime)s|%(levelname)s %(message)s',
    )

    if args.song not in config.settings['music'].keys():
        logging.fatal("Song not found in config: {}".format(args.song))
        exit(-1)

    choreographer = Choreographer(config)
    choreographer.midi_commands(config.settings['music'][args.song])
    logging.debug("Done")
