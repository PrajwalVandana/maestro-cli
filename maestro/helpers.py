from time import sleep, time


def print_to_logfile(*args, **kwargs):
    if "file" in kwargs:
        raise ValueError("file kwargs not allowed for 'print_to_logfile'")
    print(
        time(),
        *args,
        **kwargs,
        file=open(config.LOGFILE, "a", encoding="utf-8"),
    )


from maestro import (
    config,
)  # pylint: disable=wildcard-import,unused-wildcard-import

# region imports

import curses
import importlib
import logging
import multiprocessing
import os
import subprocess
import threading
import warnings

logging.disable(logging.CRITICAL)

import click
import keyring
import music_tag
import requests

from getpass import getpass
from shutil import copy, move
from random import randint
from urllib.parse import quote, quote_plus

from just_playback import Playback

try:
    from numba import jit
except:  # pylint: disable=bare-except
    jit = lambda x: x
    print_to_logfile("Numba not installed. Visualization will be slow.")
try:
    from numba.core.errors import NumbaWarning

    warnings.simplefilter("ignore", category=NumbaWarning)
except:  # pylint: disable=bare-except
    pass


try:
    import numpy as np

    LIBROSA = importlib.import_module("librosa")
    if not (
        "load" in dir(LIBROSA)
        and "amplitude_to_db" in dir(LIBROSA)
        and "stft" in dir(LIBROSA)
    ):
        raise ImportError
except ImportError:
    print_to_logfile("Librosa not installed. Visualization will be disabled.")
    LIBROSA = None


can_update_discord = True
try:
    from pypresence import Client as DiscordRPCClient
except ImportError:
    print_to_logfile(
        "pypresence not installed. Discord presence will be disabled."
    )
    can_update_discord = False

# endregion


def is_safe_username(url):
    return quote(url, safe="") == url if url else False


def bounded_shuffle(lst, radius=-1):
    """
    Randomly shuffle `lst`, but with the constraint that each element can only
    move at most `radius` positions away from its original position.

    To shuffle with no bounds, set `radius = -1`.
    """
    n = len(lst)
    if radius == -1:
        radius = n
    elif radius == 0:
        return

    index_at = list(range(n))
    for i in range(n - 1, 0, -1):
        j = randint(max(0, index_at[i] - radius), i)
        index_at[j], index_at[i] = index_at[i], index_at[j]
        lst[j], lst[i] = lst[i], lst[j]


class Scroller:
    def __init__(self, num_lines, win_size):
        self.num_lines = num_lines
        self.win_size = win_size
        self.pos = 0
        self.top = 0

    def scroll_forward(self):
        if self.pos < self.num_lines - 1:
            if (
                self.pos == self.halfway
                and self.top < self.num_lines - self.win_size
            ):
                self.top += 1
            self.pos += 1

    def scroll_backward(self):
        if self.pos > 0:
            if self.pos == self.halfway and self.top > 0:
                self.top -= 1
            self.pos -= 1

    @property
    def halfway(self):
        return self.top + (self.win_size - 1) // 2

    def resize(self, win_size=None):
        if win_size is not None:
            self.win_size = win_size
        self.top = max(0, self.pos - (self.win_size - 1) // 2)
        self.top = max(0, min(self.num_lines - self.win_size, self.top))


def fit_string_to_width(s, width, length_so_far):
    if length_so_far + len(s) > width:
        remaining_width = width - length_so_far
        if remaining_width >= 3:
            s = s[: (remaining_width - 3)] + "..."
        else:
            s = "." * remaining_width
    length_so_far += len(s)
    return s, length_so_far


def addstr_fit_to_width(stdscr, s, width, length_so_far, *args, **kwargs):
    s, length_so_far = fit_string_to_width(s, width, length_so_far)
    if s:
        if length_so_far <= width:
            stdscr.addstr(s, *args, **kwargs)
        else:
            stdscr.addstr(s[:-1], *args, **kwargs)
            stdscr.insstr(s[-1], *args, **kwargs)
    return length_so_far


@jit
def lerp(start, stop, t):
    return start + t * (stop - start)


@jit(forceobj=True)
def bin_average(arr, n, include_remainder=False, func=np.max):
    remainder = arr.shape[1] % n
    if remainder == 0:
        return func(arr.reshape(arr.shape[0], -1, n), axis=1)

    avg_head = func(arr[:, :-remainder].reshape(arr.shape[0], -1, n), axis=1)
    if include_remainder:
        avg_tail = func(
            arr[:, -remainder:].reshape(arr.shape[0], -1, remainder), axis=1
        )
        return np.concatenate((avg_head, avg_tail), axis=1)

    return avg_head


@jit(forceobj=True)
def render(
    num_bins,
    freqs,
    frame,
    visualizer_height,
    mono=None,
    include_remainder=None,
    func=np.max,
):
    """
    mono:
        True:  forces one-channel visualization
        False: forces two-channel visualization
        None:  if freqs[0] == freqs[1], one-channel, else two
    """
    if mono is None:
        mono = np.array_equal(freqs[0], freqs[1])

    if not mono:
        gap_bins = 1 if num_bins % 2 else 2
        num_bins = (num_bins - 1) // 2
    else:
        gap_bins = 0
        freqs[0, :, frame] = (freqs[0, :, frame] + freqs[1, :, frame]) / 2

    num_vertical_block_sizes = len(config.VERTICAL_BLOCKS) - 1
    freqs = np.round(
        bin_average(
            freqs[:, :, frame],
            num_bins,
            (
                (freqs.shape[-2] % num_bins) > num_bins / 2
                if include_remainder is None
                else include_remainder
            ),
            func=func,
        )
        / 80
        * visualizer_height
        * num_vertical_block_sizes
    )

    arr = np.zeros((int(not mono) + 1, visualizer_height, num_bins))
    for b in range(num_bins):
        bin_height = freqs[0, b]
        h = 0
        while bin_height > num_vertical_block_sizes:
            arr[0, h, b] = num_vertical_block_sizes
            bin_height -= num_vertical_block_sizes
            h += 1
        arr[0, h, b] = bin_height
        if not mono:
            bin_height = freqs[1, b]
            h = 0
            while bin_height > num_vertical_block_sizes:
                arr[1, h, b] = num_vertical_block_sizes
                bin_height -= num_vertical_block_sizes
                h += 1
            arr[1, h, b] = bin_height

    res = []
    for h in range(visualizer_height - 1, -1, -1):
        s = ""
        for b in range(num_bins):
            if mono:
                s += config.VERTICAL_BLOCKS[arr[0, h, b]]
            else:
                s += config.VERTICAL_BLOCKS[arr[0, h, num_bins - b - 1]]
        if not mono:
            s += " " * gap_bins
            for b in range(num_bins):
                s += config.VERTICAL_BLOCKS[arr[1, h, b]]
        res.append(s)

    return res


class FFmpegProcessHandler:
    def __init__(self, username, password):
        self.process = None
        self.username = username
        self.password = password

    def start(self):
        self.process = subprocess.Popen(
            # fmt: off
            [
                "ffmpeg",
                "-re",  # Read input at native frame rate
                "-f", "s16le",  # Raw PCM 16-bit little-endian audio
                "-ar", str(config.STREAM_SAMPLE_RATE),  # Set the audio sample rate
                "-ac", "2",  # Set the number of audio channels to 2 (stereo)
                '-i', 'pipe:',  # Input from stdin
                "-f", "mp3",  # Output format
                # "-report",  # DEBUG
                f"icecast://{self.username}:{self.password}@{config.ICECAST_SERVER}:8000/{self.username}",  # Azure-hosted maestro Icecast URL
            ],
            # fmt: on
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def terminate(self):
        if self.process is not None:
            self.process.terminate()
            self.process = None

    def restart(self):
        self.terminate()
        self.start()

    def write(self, chunk):
        if self.process is not None:
            try:
                self.process.stdin.write(chunk)
            except BrokenPipeError as e:  # pylint: disable=unused-variable
                print_to_logfile("FFmpeg processs error:", e)


class PlaybackHandler:
    def __init__(self, stdscr, playlist, clip_mode, visualize, stream, creds):
        self.stdscr = stdscr
        self.scroller = Scroller(
            len(playlist), stdscr.getmaxyx()[0] - 2  # -2 for status bar
        )
        self.playlist = playlist
        self.i = 0
        self._volume = 0
        self.clip_mode = clip_mode
        self.update_discord = False
        self.visualize = visualize  # want to visualize
        self._stream = stream
        self.username, self.password = creds

        self.playback = Playback()
        self._paused = False
        self.last_timestamp = 0
        self.looping_current_song = config.LOOP_MODES["none"]
        self.duration = 0
        self.restarting = False
        self.ending = False
        self.prompting: None | tuple = None
        self.clip = (0, 0)

        self.italic = True

        self.can_mac_now_playing = False
        self.mac_now_playing = None
        self.update_now_playing = False

        self.discord_connected = multiprocessing.Value("i", 2)
        self.discord_queues = {}

        self.can_visualize = LIBROSA is not None  # can generate visualization
        self.can_show_visualization = (
            self.visualize
            and self.can_visualize
            # space to show visualization
            and self.stdscr.getmaxyx()[0] > config.VISUALIZER_HEIGHT + 5
        )

        self.audio_data = None
        self.audio_data = {}  # dict(song_id: (vis data, stream data))
        self.audio_processing_thread = threading.Thread(
            target=self._audio_processing_loop,
            daemon=True,
        )
        self.audio_processing_thread.start()
        self.compiled = None

        # (self.stream, self.username, self.password)
        self.ffmpeg_process = FFmpegProcessHandler(self.username, self.password)
        if self.stream:
            self.ffmpeg_process.start()
        self.break_stream_loop = False
        self.img_data = None
        self.streaming_thread = threading.Thread(
            target=self._streaming_loop,
            daemon=True,
        )
        self.streaming_thread.start()

    def _load_audio(self, path, sr):
        # shape = (# channels, # frames)
        audio_data = LIBROSA.load(path, mono=False, sr=sr)[0]

        if len(audio_data.shape) == 1:  # mono -> stereo
            audio_data = np.repeat([audio_data], 2, axis=0)
        elif audio_data.shape[0] == 1:  # mono -> stereo
            audio_data = np.repeat(audio_data, 2, axis=0)
        elif audio_data.shape[0] == 6:  # 5.1 -> stereo
            audio_data = np.delete(audio_data, (1, 3, 4, 5), axis=0)

        return audio_data

    def _audio_processing_loop(self):
        while True:
            cur_song_ids = set(
                map(lambda x: x[0], self.playlist[self.i : self.i + 5])
            )
            keys_to_delete = []
            for k in self.audio_data:
                if k not in cur_song_ids:
                    keys_to_delete.append(k)
            for k in keys_to_delete:
                del self.audio_data[k]

            for i in range(self.i, min(self.i + 5, len(self.playlist))):
                song_id = self.playlist[i][0]

                if self.song_id != song_id and (
                    self.song_id not in self.audio_data
                    or (
                        self.visualize
                        and self.audio_data[self.song_id][0] is None
                    )
                    or (
                        self.stream and self.audio_data[self.song_id][1] is None
                    )
                ):
                    break
                if song_id in self.audio_data and (
                    (
                        self.audio_data[song_id][0] is not None
                        or not self.visualize
                    )
                    and (
                        self.audio_data[song_id][1] is not None
                        or not self.stream
                    )
                    or LIBROSA is None
                ):
                    continue

                song_path = os.path.join(  # NOTE: NOT SAME AS self.song_path
                    config.SETTINGS["song_directory"], self.playlist[i][1]
                )

                if song_id not in self.audio_data:
                    self.audio_data[song_id] = [
                        (
                            LIBROSA.amplitude_to_db(
                                np.abs(
                                    LIBROSA.stft(
                                        self._load_audio(
                                            song_path,
                                            sr=config.VIS_SAMPLE_RATE,
                                        )
                                    )
                                ),
                                ref=np.max,
                            )
                            + 80
                            if self.visualize and self.can_visualize
                            else None
                        ),
                        (
                            np.int16(
                                self._load_audio(
                                    song_path, sr=config.STREAM_SAMPLE_RATE
                                )
                                * (2**15 - 1)
                                * 0.5  # reduce volume (avoid clipping)
                            )  # convert to 16-bit PCM
                            if self.stream
                            else None
                        ),
                    ]
                else:
                    if (
                        self.audio_data[song_id][0] is None
                        and self.visualize
                        and self.can_visualize
                    ):
                        self.audio_data[song_id][0] = (
                            LIBROSA.amplitude_to_db(
                                np.abs(
                                    LIBROSA.stft(
                                        self._load_audio(
                                            song_path,
                                            sr=config.VIS_SAMPLE_RATE,
                                        )
                                    )
                                ),
                                ref=np.max,
                            )
                            + 80
                        )
                    if self.audio_data[song_id][1] is None and self.stream:
                        self.audio_data[song_id][1] = np.int16(
                            self._load_audio(
                                song_path, sr=config.STREAM_SAMPLE_RATE
                            )
                            * (2**15 - 1)
                            * 0.5  # reduce volume (avoid clipping)
                        )  # convert to 16-bit PCM

            sleep(1)

    def _streaming_loop(self):
        while True:
            if (
                self.stream
                and self.username is not None
                and self.audio_data is not None
                and self.song_id in self.audio_data
                and self.audio_data[self.song_id][1] is not None
                and self.playback is not None
                # is 0 for a while after resuming, and is -1 if playback is
                # inactive or file is not loaded
                and self.playback.curr_pos > 0
            ):
                for fpos in range(
                    int(self.playback.curr_pos * config.STREAM_SAMPLE_RATE),
                    self.audio_data[self.song_id][1].shape[1],
                    config.STREAM_CHUNK_SIZE,
                ):
                    try:
                        # print_to_logfile(
                        #     self.song_id,
                        #     fpos / config.STREAM_SAMPLE_RATE,
                        #     self.playback.curr_pos,
                        # )  # DEBUG
                        self.ffmpeg_process.write(
                            self.audio_data[self.song_id][1][
                                :,
                                fpos : fpos + config.STREAM_CHUNK_SIZE,
                            ]
                            .reshape((-1,), order="F")
                            .tobytes()
                            if not self.paused
                            else b"\x00" * 4 * config.STREAM_CHUNK_SIZE
                        )
                    except KeyError as e:
                        print_to_logfile("KeyError in streaming loop:", e)
                        self.update_stream_metadata()

                    if self.break_stream_loop:
                        self.break_stream_loop = False
                        break

            sleep(0.01)

    # region properties

    @property
    def paused(self):
        return self._paused

    @paused.setter
    def paused(self, value):
        self._paused = value
        self.threaded_update_icecast_metadata()

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, v):
        self._volume = v
        if self.playback is not None:
            self.playback.set_volume(v / 100)

    @property
    def stream(self):
        return self._stream

    @stream.setter
    def stream(self, value):
        if LIBROSA is None:
            value = False
        self._stream = value

    @property
    def song_id(self):
        return self.playlist[self.i][0]

    @property
    def song_file(self):
        return self.playlist[self.i][1]

    @property
    def song_path(self):
        return os.path.join(config.SETTINGS["song_directory"], self.song_file)

    @property
    def song_title(self):
        return os.path.splitext(self.song_file)[0]

    @property
    def song_artist(self):
        return self.playlist[self.i][-3]

    @property
    def song_album(self):
        return self.playlist[self.i][-2]

    @property
    def album_artist(self):
        return self.playlist[self.i][-1]

    # endregion

    def seek(self, pos):
        pos = max(0, pos)
        if self.playback is not None:
            self.playback.seek(pos)
            self.break_stream_loop = True
            self.threaded_update_icecast_metadata()
            if self.can_mac_now_playing and self.mac_now_playing is not None:
                self.mac_now_playing.pos = round(pos)
                self.update_now_playing = True
            self.last_timestamp = pos

    def set_volume(self, v):
        """Set volume w/o changing self.volume."""
        self.playback.set_volume(v / 100)

    def quit(self):
        if self.ffmpeg_process is not None:
            self.ffmpeg_process.terminate()

    def prompting_delete_char(self):
        if self.prompting[1] > 0:
            self.prompting = (
                self.prompting[0][: self.prompting[1] - 1]
                + self.prompting[0][self.prompting[1] :],
                self.prompting[1] - 1,
                self.prompting[2],
            )

    def update_screen(self):
        self.output(self.playback.curr_pos)

    def update_discord_metadata(self):
        if self.update_discord:
            multiprocessing_put_word(
                self.discord_queues["title"],
                self.song_title,
            )
            multiprocessing_put_word(
                self.discord_queues["artist"],
                self.song_artist,
            )
            multiprocessing_put_word(
                self.discord_queues["album"],
                self.song_album,
            )

    def update_mac_now_playing_metadata(self):
        if self.can_mac_now_playing:
            self.mac_now_playing.paused = False
            self.mac_now_playing.pos = 0
            self.mac_now_playing.length = self.duration
            self.mac_now_playing.cover = self.img_data

            multiprocessing_put_word(
                self.mac_now_playing.title_queue,
                self.song_title,
            )
            multiprocessing_put_word(
                self.mac_now_playing.artist_queue,
                self.song_artist,
            )

            self.update_now_playing = True

    def _update_icecast_metadata(self):
        # self.break_stream_loop = True
        return requests.post(
            config.UPDATE_METADATA_URL,
            data={
                "mount": self.username,
                "song": quote_plus(self.song_title),
                "artist": quote_plus(self.song_artist),
                "album": quote_plus(self.song_album),
                "albumartist": quote_plus(self.album_artist),
                "duration": self.duration,
                "paused": int(self.paused),
            },
            auth=(self.username, self.password),
            timeout=5,
        )

    def update_icecast_metadata(self):
        success = False
        last_metadata_update_attempt = 0
        while not success:
            t = time()
            if t - last_metadata_update_attempt > 5:
                try:
                    response = self._update_icecast_metadata()
                    if response.ok:
                        last_metadata_update_attempt = 0
                        success = True
                    else:
                        raise Exception(
                            f"Icecast Server error {response.status_code}: {response.text}"
                        )
                except Exception as e:  # retry in 5 seconds
                    print_to_logfile("Update metadata failed:", e)
                    last_metadata_update_attempt = t
            sleep(0.01)

    def threaded_update_icecast_metadata(self):
        threading.Thread(
            target=self.update_icecast_metadata, daemon=True
        ).start()

    def update_stream_metadata(self):
        self.break_stream_loop = True
        if not requests.post(
            config.UPDATE_ARTWORK_URL,
            params={"mount": self.username},
            files={"artwork": self.img_data},
            auth=(self.username, self.password),
            timeout=5,
        ).ok:
            print_to_logfile("Failed to update artwork.")

        if not requests.post(
            config.UPDATE_TIMESTAMP_URL,
            params={"mount": self.username},
            data={
                "timestamp": self.playback.curr_pos,
                "time_updated": time(),
            },
            auth=(self.username, self.password),
            timeout=5,
        ).ok:
            print_to_logfile("Failed to update timestamp.")

        self.threaded_update_icecast_metadata()

    def update_metadata(self):
        def f():
            song_data = music_tag.load_file(self.song_path)
            self.img_data = (
                song_data["artwork"].first.raw_thumbnail([600, 600])
                if "artwork" in song_data
                else None
            )

            self.update_mac_now_playing_metadata()
            if self.stream:
                self.update_stream_metadata()
            self.update_discord_metadata()

        threading.Thread(target=f, daemon=True).start()

    def initialize_discord_attrs(self):
        self.update_discord = True
        self.discord_queues["title"] = multiprocessing.Queue()
        self.discord_queues["artist"] = multiprocessing.Queue()
        self.discord_queues["album"] = multiprocessing.Queue()

    def output(self, pos):
        self.can_show_visualization = (
            self.visualize
            and self.can_visualize
            and self.stdscr.getmaxyx()[0] > config.VISUALIZER_HEIGHT + 5
        )
        self.scroller.resize(
            self.stdscr.getmaxyx()[0]
            - 3  # -3 for status bar
            - 1  # -1 for header
            - (self.prompting != None)  # - add mode
            # - visualizer
            - (config.VISUALIZER_HEIGHT if self.can_show_visualization else 0)
        )

        if self.clip_mode:
            pos -= self.clip[0]

        self.stdscr.erase()

        screen_width = self.stdscr.getmaxyx()[1]

        length_so_far = 0
        if self.update_discord:
            if self.discord_connected.value == 2:
                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    "Connecting to Discord ... ",
                    screen_width,
                    length_so_far,
                    curses.color_pair(12),
                )
            elif self.discord_connected.value == 1:
                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    "Discord connected! ",
                    screen_width,
                    length_so_far,
                    curses.color_pair(17),
                )
            else:
                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    "Failed to connect to Discord. ",
                    screen_width,
                    length_so_far,
                    curses.color_pair(14),
                )

        visualize_message = ""
        visualize_color = 12
        if self.visualize:
            if self.audio_data is None and self.can_visualize:
                self.audio_processing_thread = threading.Thread(
                    target=self._audio_processing_loop,
                    daemon=True,
                )
                self.audio_data = {}
                self.audio_processing_thread.start()

            if not self.can_visualize:
                visualize_message = "Librosa is required for visualization."
                visualize_color = 14
            elif not self.can_show_visualization:
                visualize_message = "Window too small for visualization."
                visualize_color = 14
            elif self.song_id not in self.audio_data:
                visualize_message = "Loading visualization..."
                visualize_color = 12
            elif not self.compiled:
                visualize_message = "Compiling renderer..."
                visualize_color = 12

        if self.stream:
            prefix = "  " if self.update_discord else ""
            if self.username:
                long_stream_message = (
                    prefix
                    + f"Streaming at {config.MAESTRO_SITE}/listen/{self.username}!"
                )
                short_stream_message = prefix + f"Streaming as {self.username}!"
                if (
                    length_so_far
                    + len(long_stream_message)
                    + 2
                    + (len(visualize_message) if visualize_message else -2)
                    < screen_width
                ):
                    length_so_far = addstr_fit_to_width(
                        self.stdscr,
                        long_stream_message,
                        screen_width,
                        length_so_far,
                        curses.color_pair(16),
                    )
                else:
                    length_so_far = addstr_fit_to_width(
                        self.stdscr,
                        short_stream_message,
                        screen_width,
                        length_so_far,
                        curses.color_pair(16),
                    )
            else:
                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    prefix + "Please log in to stream.",
                    screen_width,
                    length_so_far,
                    curses.color_pair(14),
                )

        length_so_far = addstr_fit_to_width(
            self.stdscr,
            " " * (screen_width - length_so_far - len(visualize_message))
            + visualize_message,
            screen_width,
            length_so_far,
            curses.color_pair(visualize_color),
        )
        self.stdscr.move(1, 0)

        song_display_color = 5 if self.looping_current_song else 3
        progress_bar_display_color = (
            17 if (self.clip_mode and self.clip != (0, self.duration)) else 15
        )

        # for aligning song names
        longest_song_id_length = max(len(song[0]) for song in self.playlist)

        for j in range(
            self.scroller.top, self.scroller.top + self.scroller.win_size
        ):
            if j <= len(self.playlist) - 1:
                length_so_far = 0

                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    " " * (longest_song_id_length - len(self.playlist[j][0]))
                    + f"{self.playlist[j][0]} ",
                    screen_width,
                    length_so_far,
                    curses.color_pair(2),
                )
                if j == self.i:
                    length_so_far = addstr_fit_to_width(
                        self.stdscr,
                        f"{self.playlist[j][1]} ",
                        screen_width,
                        length_so_far,
                        curses.color_pair(song_display_color) | curses.A_BOLD,
                    )
                else:
                    length_so_far = addstr_fit_to_width(
                        self.stdscr,
                        f"{self.playlist[j][1]} ",
                        screen_width,
                        length_so_far,
                        (
                            curses.color_pair(4)
                            if (j == self.scroller.pos)
                            else curses.color_pair(1)
                        ),
                    )
                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    f"{', '.join(self.playlist[j][2].split(','))}",
                    screen_width,
                    length_so_far,
                    curses.color_pair(2),
                )
            self.stdscr.move((j - self.scroller.top) + 2, 0)

        if self.prompting is not None:
            # pylint: disable=unsubscriptable-object
            if (
                self.prompting[2] == config.PROMPT_MODES["add"]
                or self.prompting[2] == config.PROMPT_MODES["insert"]
            ):
                adding_song_length = addstr_fit_to_width(
                    self.stdscr,
                    (
                        "Insert"
                        if self.prompting[2] == config.PROMPT_MODES["insert"]
                        else "Append"
                    )
                    + " song (by ID): "
                    + self.prompting[0],
                    screen_width,
                    0,
                    curses.color_pair(1),
                )
            else:
                adding_song_length = addstr_fit_to_width(
                    self.stdscr,
                    "Add tag to songs: " + self.prompting[0],
                    screen_width,
                    0,
                    curses.color_pair(1),
                )
            self.stdscr.move(self.stdscr.getyx()[0] + 1, 0)

        length_so_far = 0

        length_so_far = addstr_fit_to_width(
            self.stdscr,
            ("| " if self.paused else "> ") + f"({self.song_id}) ",
            screen_width,
            length_so_far,
            curses.color_pair(song_display_color + 10),
        )
        length_so_far = addstr_fit_to_width(
            self.stdscr,
            f"{self.song_file} ",
            screen_width,
            length_so_far,
            curses.color_pair(song_display_color + 10) | curses.A_BOLD,
        )
        length_so_far = addstr_fit_to_width(
            self.stdscr,
            "%d/%d  " % (self.i + 1, len(self.playlist)),
            screen_width,
            length_so_far,
            curses.color_pair(12),
        )
        length_so_far = addstr_fit_to_width(
            self.stdscr,
            f"{'c' if self.clip_mode else ' '}",
            screen_width,
            length_so_far,
            curses.color_pair(17) | curses.A_BOLD,
        )

        loop_char = " "
        if self.looping_current_song == config.LOOP_MODES["one"]:
            loop_char = "l"
        elif self.looping_current_song == config.LOOP_MODES["inf"]:
            loop_char = "L"
        length_so_far = addstr_fit_to_width(
            self.stdscr,
            loop_char,
            screen_width,
            length_so_far,
            curses.color_pair(15) | curses.A_BOLD,
        )

        volume_line_length_so_far = addstr_fit_to_width(
            self.stdscr,
            f"{'e' if self.ending else ' '}  ",
            screen_width,
            length_so_far,
            curses.color_pair(14) | curses.A_BOLD,
        )
        addstr_fit_to_width(
            self.stdscr,
            " " * (screen_width - volume_line_length_so_far - 1),
            screen_width,
            volume_line_length_so_far,
            curses.color_pair(16),
        )
        self.stdscr.insstr(  # hacky fix for curses bug
            " ",
            curses.color_pair(16),
        )
        self.stdscr.move(
            self.stdscr.getmaxyx()[0]
            - 2
            - (config.VISUALIZER_HEIGHT if self.can_show_visualization else 0),
            0,
        )

        addstr_fit_to_width(
            self.stdscr,
            " " * (screen_width - 1),
            screen_width,
            0,
            curses.color_pair(16),
        )
        self.stdscr.insstr(  # hacky fix for curses bug
            " ",
            curses.color_pair(16),
        )
        self.stdscr.move(
            self.stdscr.getyx()[0],
            0,
        )

        song_data_length_so_far = addstr_fit_to_width(
            self.stdscr,
            self.song_artist + " - ",
            screen_width,
            0,
            curses.color_pair(12),
        )

        if self.italic:
            try:
                song_data_length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    self.song_album,
                    screen_width,
                    song_data_length_so_far,
                    curses.color_pair(12) | curses.A_ITALIC,
                )
            except:  # pylint: disable=bare-except
                self.italic = False
                print_to_logfile("Failed to italicize text in curses.")
        if not self.italic:
            song_data_length_so_far = addstr_fit_to_width(
                self.stdscr,
                self.song_album,
                screen_width,
                song_data_length_so_far,
                curses.color_pair(12),
            )

        addstr_fit_to_width(
            self.stdscr,
            f" ({self.album_artist})",
            screen_width,
            song_data_length_so_far,
            curses.color_pair(12),
        )

        self.stdscr.move(
            self.stdscr.getmaxyx()[0]
            - (config.VISUALIZER_HEIGHT if self.can_show_visualization else 0)
            - 1,
            0,
        )

        length_so_far = 0
        secs = int(pos)
        length_so_far = addstr_fit_to_width(
            self.stdscr,
            f"{format_seconds(secs)} / {format_seconds(self.duration)}  ",
            screen_width,
            length_so_far,
            curses.color_pair(progress_bar_display_color),
        )
        if not length_so_far >= screen_width:
            if (
                screen_width - length_so_far
                >= config.MIN_PROGRESS_BAR_WIDTH + 2
            ):
                progress_bar_width = screen_width - length_so_far - 2
                bar = "|"
                progress_block_width = (
                    progress_bar_width * 8 * pos
                ) // self.duration
                for _ in range(progress_bar_width):
                    if progress_block_width > 8:
                        bar += config.HORIZONTAL_BLOCKS[8]
                        progress_block_width -= 8
                    elif progress_block_width > 0:
                        bar += config.HORIZONTAL_BLOCKS[progress_block_width]
                        progress_block_width = 0
                    else:
                        bar += " "

                self.stdscr.addstr(
                    bar, curses.color_pair(progress_bar_display_color)
                )
                self.stdscr.insstr(  # hacky fix for curses bug
                    "|", curses.color_pair(progress_bar_display_color)
                )
            else:
                self.stdscr.addstr(
                    " " * (screen_width - length_so_far - 1),
                    curses.color_pair(16),
                )
                self.stdscr.insstr(  # hacky fix for curses bug
                    " ", curses.color_pair(16)
                )

        # right align volume bar
        if not volume_line_length_so_far >= screen_width:
            self.stdscr.move(
                self.stdscr.getmaxyx()[0]
                - 3
                - (
                    config.VISUALIZER_HEIGHT
                    if self.can_show_visualization
                    else 0
                ),
                volume_line_length_so_far,
            )
            if (
                screen_width - volume_line_length_so_far
                >= config.MIN_VOLUME_BAR_WIDTH + 10
            ):
                bar = f"{str(int(self.volume)).rjust(3)}/100 |"
                volume_bar_width = min(
                    screen_width - volume_line_length_so_far - (len(bar) + 1),
                    config.MAX_VOLUME_BAR_WIDTH,
                )
                block_width = int(volume_bar_width * 8 * self.volume / 100)
                for _ in range(volume_bar_width):
                    if block_width > 8:
                        bar += config.HORIZONTAL_BLOCKS[8]
                        block_width -= 8
                    elif block_width > 0:
                        bar += config.HORIZONTAL_BLOCKS[block_width]
                        block_width = 0
                    else:
                        bar += " "
                bar += "|"
                bar = bar.rjust(screen_width - volume_line_length_so_far)

                self.stdscr.addstr(bar, curses.color_pair(16))
            elif screen_width - volume_line_length_so_far >= 7:
                self.stdscr.addstr(
                    f"{str(int(self.volume)).rjust(3)}/100".rjust(
                        screen_width - volume_line_length_so_far
                    ),
                    curses.color_pair(16),
                )

        if self.can_show_visualization:
            if self.clip_mode:
                pos += self.clip[0]

            self.stdscr.move(
                self.stdscr.getmaxyx()[0]
                - (
                    config.VISUALIZER_HEIGHT
                    if self.can_show_visualization
                    else 0
                ),
                0,
            )
            if (
                self.song_id not in self.audio_data
                or self.audio_data[self.song_id][0] is None
            ):
                self.stdscr.addstr(
                    (
                        (" " * (self.stdscr.getmaxyx()[1] - 1) + "\n")
                        * config.VISUALIZER_HEIGHT
                    ).rstrip()
                )
            elif not self.compiled:
                if self.compiled is None:
                    self.compiled = False

                    def thread_func():
                        vdata = self.audio_data[self.song_id][0]
                        render(
                            self.stdscr.getmaxyx()[1],
                            vdata,
                            min(round(pos * config.FPS), vdata.shape[2] - 1),
                            config.VISUALIZER_HEIGHT,
                        )
                        self.compiled = True

                    t = threading.Thread(target=thread_func, daemon=True)
                    t.start()
                self.stdscr.addstr(
                    (
                        (" " * (self.stdscr.getmaxyx()[1] - 1) + "\n")
                        * config.VISUALIZER_HEIGHT
                    ).rstrip()
                )
            elif self.compiled:
                vdata = self.audio_data[self.song_id][0]
                rendered_lines = render(
                    self.stdscr.getmaxyx()[1],
                    vdata,
                    min(
                        round(pos * config.FPS),
                        # fmt: off
                        vdata.shape[2] - 1,
                    ),
                    config.VISUALIZER_HEIGHT,
                )
                for i in range(len(rendered_lines)):
                    self.stdscr.addstr(rendered_lines[i][:-1])
                    self.stdscr.insstr(rendered_lines[i][-1])
                    if i < len(rendered_lines) - 1:
                        self.stdscr.move(self.stdscr.getyx()[0] + 1, 0)

        if self.prompting is not None:
            # pylint: disable=unsubscriptable-object
            self.stdscr.move(
                self.stdscr.getmaxyx()[0]
                - (
                    config.VISUALIZER_HEIGHT
                    if self.can_show_visualization
                    else 0
                )
                - 4,  # 4 lines for status bar + adding entry
                adding_song_length
                + (self.prompting[1] - len(self.prompting[0])),
            )

        self.stdscr.refresh()


def init_curses(stdscr):
    curses.start_color()
    curses.use_default_colors()

    # region colors

    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_BLACK + 8, -1)  # bright black
    curses.init_pair(3, curses.COLOR_BLUE, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_YELLOW, -1)
    curses.init_pair(6, curses.COLOR_GREEN, -1)
    curses.init_pair(7, curses.COLOR_MAGENTA, -1)

    curses.init_pair(12, curses.COLOR_BLACK + 8, curses.COLOR_BLACK)
    curses.init_pair(13, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(14, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(15, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(16, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(17, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
    # endregion

    curses.curs_set(False)
    stdscr.nodelay(True)
    try:
        curses.set_escdelay(25)  # 25 ms
    except:  # pylint: disable=bare-except
        pass


class SongParamType(click.ParamType):
    name = "song"

    def convert(self, value, param, ctx):
        if type(value) == int:
            return value

        if not value.isdecimal():
            results = search_song(value)
            if not any(results):
                self.fail(f"No song found matching '{value}'.", param, ctx)

            for result in results:
                if len(result) == 1:
                    return int(result[0][0])
                if len(result) > 1:
                    break

            for details in sum(results, []):
                print_entry(details, value)
            self.fail("Multiple songs found", param, ctx)

        song_id = int(value)
        if song_id < 1:
            self.fail("Song ID must be positive.", param, ctx)
        return song_id


SONG = SongParamType()


def embed_artwork(yt_dlp_info):
    yt_dlp_info["thumbnails"].sort(key=lambda d: d["preference"])
    best_thumbnail = yt_dlp_info["thumbnails"][-1]  # default thumbnail

    if "width" not in best_thumbnail:
        # diff so that any square thumbnail is chosen
        best_thumbnail["width"] = 0
        best_thumbnail["height"] = -1

    for thumbnail in yt_dlp_info["thumbnails"][:-1]:
        if "height" in thumbnail and (
            thumbnail["height"] == thumbnail["width"]
            and (best_thumbnail["width"] != best_thumbnail["height"])
            or (
                thumbnail["height"] >= best_thumbnail["height"]
                and (thumbnail["width"] >= best_thumbnail["width"])
                and (
                    (best_thumbnail["width"] != best_thumbnail["height"])
                    or thumbnail["width"] == thumbnail["height"]
                )
            )
        ):
            best_thumbnail = thumbnail

    image_url = best_thumbnail["url"]
    response = requests.get(image_url, timeout=5)
    image_data = response.content

    m = music_tag.load_file(yt_dlp_info["requested_downloads"][0]["filepath"])
    m["artwork"] = image_data
    m.save()


def discord_join_event_handler(arg):
    print_to_logfile("Join event:", arg)


def connect_to_discord():
    discord_rpc = DiscordRPCClient(client_id=config.DISCORD_ID)
    discord_rpc.start()
    # discord_rpc.register_event(
    #     "ACTIVITY_JOIN",
    #     discord_join_event_handler,
    # )
    return discord_rpc


def add_song(
    path,
    tags,
    move_,
    songs_file,
    lines,
    song_id,
    prepend_newline,
    clip_start,
    clip_end,
    skip_dupes,
):
    song_fname = os.path.split(path)[1]
    if "|" in song_fname:
        song_fname = song_fname.replace("|", "-")
        click.secho(
            f"The song \"{song_fname}\" contains one or more '|' characters, which are not allowed—all ocurrences have been replaced with '-'.",
            fg="yellow",
        )

    for line in lines:
        details = line.split("|")
        song_name, song_ext = os.path.splitext(song_fname)
        if os.path.splitext(details[1])[0] == song_name:
            if skip_dupes:
                click.secho(
                    f"Song with name '{song_name}' already exists, skipping.",
                    fg="yellow",
                )
                os.remove(path)
                return
            click.secho(
                f"Song with name '{song_name}' already exists, 'copy' will be appended to the song name.",
                fg="yellow",
            )
            song_fname = song_name + " copy" + song_ext
            break

    dest_path = os.path.join(config.SETTINGS["song_directory"], song_fname)

    if move_:
        move(path, dest_path)
    else:
        copy(path, dest_path)

    tags = list(set(tags))

    if prepend_newline:
        songs_file.write("\n")
    songs_file.write(f"{song_id}|{song_fname}|{','.join(tags)}|")
    if clip_start is not None:
        songs_file.write(f"{clip_start} {clip_end}")
    songs_file.write("\n")

    for stats_file in os.listdir(config.STATS_DIR):
        if not stats_file.endswith(".txt"):
            continue

        with open(
            os.path.join(config.STATS_DIR, stats_file), "r+", encoding="utf-8"
        ) as stats_file:
            stats_file_contents = stats_file.read()
            if stats_file_contents and not stats_file_contents.endswith("\n"):
                stats_file.write("\n")
            stats_file.write(f"{song_id}|0\n")

    if not tags:
        tags_string = ""
    elif len(tags) == 1:
        tags_string = f" and tag '{tags[0]}'"
    else:
        tags_string = f" and tags {', '.join([repr(tag) for tag in tags])}"

    if clip_start is not None:
        clip_string = f" and clip [{format_seconds(clip_start, show_decimal=True)}, {format_seconds(clip_end, show_decimal=True)}]"
    else:
        clip_string = ""

    song_metadata = music_tag.load_file(dest_path)
    click.secho(
        f"Added song '{song_fname}' with ID {song_id}"
        + tags_string
        + clip_string
        + f" and metadata (artist: {song_metadata['artist'] if song_metadata['artist'] else '<None>'}, album: {song_metadata['album'] if song_metadata['album'] else '<None>'}, albumartist: {song_metadata['albumartist'] if song_metadata['albumartist'] else '<None>'}).",
        fg="green",
    )


def clip_editor(stdscr, details, start=None, end=None):
    song_name = details[1]
    song_path = os.path.join(config.SETTINGS["song_directory"], song_name)

    playback = Playback()
    playback.load_file(song_path)

    init_curses(stdscr)

    if details[3]:
        clip_start, clip_end = [float(x) for x in details[3].split()]
    else:
        clip_start, clip_end = 0, playback.duration

    if start is not None:
        clip_start = start
    if end is not None:
        clip_end = end

    editing_start = True
    change_output = True
    playback.play()
    playback.pause()
    playback.seek(clip_start)
    last_timestamp = playback.curr_pos
    while True:
        if playback.curr_pos >= clip_end:
            playback.pause()

        change_output = change_output or (
            (playback.curr_pos - last_timestamp)
            >= (playback.duration / (8 * (stdscr.getmaxyx()[1] - 2)))
        )

        if change_output:
            clip_editor_output(
                stdscr,
                details,
                playback.curr_pos,
                playback.paused,
                playback.duration,
                clip_start,
                clip_end,
                editing_start,
            )

        c = stdscr.getch()
        next_c = stdscr.getch()
        while next_c != -1:
            c, next_c = next_c, stdscr.getch()

        if c == -1:
            continue

        change_output = False
        if editing_start:
            if c == curses.KEY_LEFT:
                change_output = True
                playback.pause()
                clip_start = max(0, clip_start - 0.1)
                playback.seek(clip_start)
            elif c == curses.KEY_SLEFT:
                change_output = True
                playback.pause()
                clip_start = max(0, clip_start - 1)
                playback.seek(clip_start)
            elif c == curses.KEY_RIGHT:
                change_output = True
                playback.pause()
                clip_start = min(clip_start + 0.1, clip_end)
                playback.seek(clip_start)
            elif c == curses.KEY_SRIGHT:
                change_output = True
                playback.pause()
                clip_start = min(clip_start + 1, clip_end)
                playback.seek(clip_start)
            elif c == curses.KEY_ENTER:
                break
            else:
                c = chr(c)
                if c == " ":  # space
                    change_output = True
                    if playback.playing:
                        playback.pause()
                    else:
                        playback.resume()
                elif c in "tT":
                    change_output = True
                    playback.pause()
                    playback.seek(clip_end - 1)
                    editing_start = False
                elif c in "qQ":
                    return (None, None)
                elif c in "\r\n":
                    break
        else:
            if c == curses.KEY_LEFT:
                change_output = True
                playback.pause()
                clip_end = max(clip_end - 0.1, clip_start)
                playback.seek(clip_end - 1)
            elif c == curses.KEY_SLEFT:
                change_output = True
                playback.pause()
                clip_end = max(clip_end - 1, clip_start)
                playback.seek(clip_end - 1)
            elif c == curses.KEY_RIGHT:
                change_output = True
                playback.pause()
                clip_end = min(clip_end + 0.1, playback.duration)
                playback.seek(clip_end - 1)
            elif c == curses.KEY_SRIGHT:
                change_output = True
                playback.pause()
                clip_end = min(clip_end + 1, playback.duration)
                playback.seek(clip_end - 1)
            elif c == curses.KEY_ENTER:
                break
            else:
                c = chr(c)
                if c == " ":
                    change_output = True
                    if playback.playing:
                        playback.pause()
                    else:
                        playback.resume()
                elif c in "tT":
                    change_output = True
                    playback.pause()
                    playback.seek(clip_start)
                    editing_start = True
                elif c in "qQ":
                    return (None, None)
                elif c in "\r\n":
                    break

    return clip_start, clip_end


def clip_editor_output(
    stdscr,
    details,
    pos,
    paused,
    duration,
    clip_start,
    clip_end,
    editing_start,
):
    stdscr.erase()

    if stdscr.getmaxyx()[0] < 3:
        stdscr.addstr("Window too small.", curses.color_pair(4))
        stdscr.refresh()
        return

    screen_width = stdscr.getmaxyx()[1]

    stdscr.insstr(
        f"{format_seconds(clip_start, show_decimal=True)}"
        + (" <" if editing_start else ""),
        curses.color_pair(7),
    )

    end_str = (
        "> " if not editing_start else ""
    ) + f"{format_seconds(clip_end, show_decimal=True)}"
    stdscr.move(0, screen_width - len(end_str))
    stdscr.insstr(end_str, curses.color_pair(7))

    stdscr.move(1, 0)

    clip_bar_width = screen_width - 2
    if clip_bar_width > 0:
        bar = "|"
        before_clip_block_width = round(
            (clip_bar_width * 8 * clip_start) / duration
        )
        clip_block_width = round(
            clip_bar_width * 8 * (clip_end - clip_start) / duration
        )
        num_chars_added = 0
        stdscr.addstr("|", curses.color_pair(7))
        while before_clip_block_width:
            if before_clip_block_width >= 8:
                stdscr.addstr(" ", curses.color_pair(7))
                before_clip_block_width -= 8
            else:
                stdscr.addstr(
                    config.HORIZONTAL_BLOCKS[before_clip_block_width],
                    curses.color_pair(7) | curses.A_REVERSE,
                )
                clip_block_width -= 8 - before_clip_block_width
                before_clip_block_width = 0
            num_chars_added += 1

        while num_chars_added < clip_bar_width:
            if clip_block_width >= 8:
                stdscr.addstr(config.HORIZONTAL_BLOCKS[8], curses.color_pair(7))
                clip_block_width -= 8
            elif clip_block_width > 0:
                stdscr.addstr(
                    config.HORIZONTAL_BLOCKS[clip_block_width],
                    curses.color_pair(7),
                )
                clip_block_width = 0
            else:
                stdscr.addstr(" ", curses.color_pair(7))
            num_chars_added += 1
        stdscr.insstr("|", curses.color_pair(7))
        stdscr.move(stdscr.getyx()[0] + 1, 0)

    progress_bar_width = screen_width - 2
    if progress_bar_width > 0:
        bar = "|"
        progress_block_width = (progress_bar_width * 8 * pos) // duration
        for _ in range(progress_bar_width):
            if progress_block_width > 8:
                bar += config.HORIZONTAL_BLOCKS[8]
                progress_block_width -= 8
            elif progress_block_width > 0:
                bar += config.HORIZONTAL_BLOCKS[progress_block_width]
                progress_block_width = 0
            else:
                bar += " "

        stdscr.addstr(bar, curses.color_pair(5))
        stdscr.insstr("|", curses.color_pair(5))  # hacky fix for curses bug
        stdscr.move(stdscr.getyx()[0] + 1, 0)

    length_so_far = 0
    length_so_far = addstr_fit_to_width(
        stdscr,
        ("| " if paused else "> ") + f"({details[0]}) ",
        screen_width,
        length_so_far,
        curses.color_pair(3),
    )
    length_so_far = addstr_fit_to_width(
        stdscr,
        f"{details[1]} ",
        screen_width,
        length_so_far,
        curses.color_pair(3) | curses.A_BOLD,
    )
    length_so_far = addstr_fit_to_width(
        stdscr,
        f"{', '.join(details[2].split(','))} ",
        screen_width,
        length_so_far,
        curses.color_pair(2),
    )

    stdscr.refresh()


def get_username():
    return keyring.get_password("maestro-music", "username")


def get_password():
    return keyring.get_password("maestro-music", "password")


def signup(username=None, password=None, login_=True):
    if username is None:
        username = input("Username: ")

    if not username:
        click.secho("Username cannot be empty.", fg="red")
        return
    if not is_safe_username(username):
        click.secho(
            "Username must be URL-safe (no spaces or special characters).",
            fg="red",
        )
        return

    response = requests.get(
        config.USER_EXISTS_URL, params={"user": username}, timeout=5
    )
    if response.status_code == 200:
        click.secho(f"Username {username} already exists.", fg="red")
        return

    if password is None:
        password = getpass("Password (8-1024 characters):")
        if len(password) < 8 or len(password) > 1024:
            click.secho("Passwords should be 8-1024 characters long.", fg="red")
            return
    confirm_password = getpass("Confirm password:")
    if password != confirm_password:
        click.secho("Passwords do not match.", fg="red")
        return

    response = requests.post(
        config.SIGNUP_URL, auth=(username, password), timeout=5
    )
    if response.status_code == 201:
        click.secho(f"Successfully signed up user '{username}'!", fg="green")
        if login_:
            login(username, password)
    else:
        click.secho(
            f"Signup failed with status code {response.status_code}: {response.text}",
            fg="red",
        )


def login(username=None, password=None):
    if username is None:
        username = input("Username: ")

    if not username:
        click.secho("Username cannot be empty.", fg="red")
        return
    if not is_safe_username(username):
        click.secho(
            "Username must be URL-safe (no spaces or special characters).",
            fg="red",
        )
        return

    current_username = keyring.get_password("maestro-music", "username")
    if current_username == username:
        click.secho(f"User '{username}' is already logged in.", fg="yellow")
        return
    if current_username is not None:
        click.secho(
            f"Logging in as user '{username}' will log out current user '{current_username}'.",
            fg="yellow",
        )

    if password is None:
        password = getpass("Password:")

    response = requests.post(
        config.LOGIN_URL, auth=(username, password), timeout=5
    )
    if response.status_code == 200:
        click.secho(f"Successfully logged in user '{username}'!", fg="green")
        keyring.set_password("maestro-music", "username", username)
        keyring.set_password("maestro-music", "password", password)
    else:
        click.secho(
            f"Login failed with status code {response.status_code}: {response.text}",
            fg="red",
        )


def format_seconds(secs, show_decimal=False, digital=True, include_hours=None):
    """Format seconds into a string.

    show_decimal: whether to show the decimal part of the seconds
    digital: whether to use digital format ([HH]:MM:SS) or words (e.g. 1h 2m 3s)
    include_hours: whether to include hours in the output (e.g. 71:05 vs 1:11:05)
    """
    h = int(secs // 3600)
    if include_hours is None:
        include_hours = h > 0
    m = int(secs // 60)
    if include_hours:
        m %= 60
    s = int(secs % 60)
    if digital:
        return (
            (f"{h}:" if include_hours else "")
            + f"{m}:{s:02}"
            + (f".{secs%1:0.2f}"[2:] if show_decimal else "")
        )
    return (
        (f"{h}h " if include_hours else "")
        + f"{m}m {s}"
        + (f".{secs%1:0.2f}"[2:] if show_decimal else "")
        + "s"
    )


def search_song(phrase, songs_file=None):
    """
    CASE INSENSITIVE. Returns a tuple of three lists:
    0: songs that are the phrase
    1: songs that start with the phrase
    1: songs that contain the phrase but do not start with it
    """
    songs_file = songs_file or open(
        config.SONGS_INFO_PATH, "r", encoding="utf-8"
    )
    phrase = phrase.lower()

    results = [], [], []  # is, starts, contains but does not start
    for line in songs_file:
        details = line.strip().split("|")
        song_name = os.path.splitext(details[1].lower())[0]

        if song_name == phrase:
            results[0].append(details)
        elif song_name.startswith(phrase):
            results[1].append(details)
        elif phrase in song_name:
            results[2].append(details)

    return results


def print_entry(entry_list, highlight=None, show_song_info=False):
    """
    tuple or iterable of STRINGS

    0: song ID
    1: song name
    2: tags
    3: clip

    optional:
    4: seconds listened
    5: total duration (must be passed if 4 is passed)

    Pretty prints ([] means optional)
        <song ID> <song name> [<total duration> <seconds listened> <times listened>] <clip> <tags>
            [<artist> - <album> (<album artist>)]
    """
    click.secho(entry_list[0] + " ", fg="bright_black", nl=False)
    if highlight is None:
        click.secho(entry_list[1] + " ", fg="blue", nl=False, bold=True)
    else:
        highlight_loc = entry_list[1].lower().find(highlight.lower())
        click.secho(
            entry_list[1][:highlight_loc],
            fg="white",
            nl=False,
        )
        click.secho(
            entry_list[1][highlight_loc : highlight_loc + len(highlight)],
            fg="blue",
            nl=False,
            bold=True,
        )
        click.secho(
            entry_list[1][highlight_loc + len(highlight) :] + " ",
            fg="white",
            nl=False,
        )

    if len(entry_list) > 4:  # len should == 6
        secs_listened = float(entry_list[4])
        total_duration = float(entry_list[5])
        click.secho(
            format_seconds(
                total_duration,
                show_decimal=True,
                digital=False,
            )
            + " ",
            nl=False,
        )
        click.secho(
            format_seconds(
                secs_listened,
                show_decimal=True,
                digital=False,
            )
            + " ",
            fg="yellow",
            nl=False,
        )
        click.secho(
            f"{secs_listened / total_duration:0.2f} ", fg="green", nl=False
        )

    if entry_list[3]:
        decimal_format_seconds = lambda x: format_seconds(
            float(x), show_decimal=True
        )
        start, end = map(decimal_format_seconds, entry_list[3].split())
        click.secho(
            f"[{start}, {end}] ",
            fg="magenta",
            nl=False,
        )

    if entry_list[2]:
        click.secho(", ".join(entry_list[2].split(",")), fg="bright_black")
    else:
        click.echo()  # newline

    if show_song_info:
        song_data = music_tag.load_file(
            os.path.join(config.SETTINGS["song_directory"], entry_list[1])
        )
        artist, album, album_artist = (
            song_data["artist"].value,
            song_data["album"].value,
            song_data["albumartist"].value,
        )
        click.secho(
            f"{(len(entry_list[0])+1)*' '}{artist if artist else 'No Artist'} - ",
            fg="bright_black",
            nl=False,
        )
        click.secho(
            (album if album else "No Album"),
            italic=True,
            fg="bright_black",
            nl=False,
        )
        click.secho(
            f" ({album_artist if album_artist else 'No Album Artist'})",
            fg="bright_black",
        )


def multiprocessing_put_word(q, word):
    for c in word:
        q.put(c)
    q.put("\n")


def versiontuple(v):
    return tuple(map(int, v.split(".")))


def pluralize(count, word, include_count=True):
    return f"{count} " * include_count + word + ("s" if count != 1 else "")
