# region imports

import atexit
import curses
import logging
import os
import subprocess
import threading

logging.disable(logging.CRITICAL)

import click
import msgspec

from getpass import getpass
from random import randint
from time import sleep, time
from typing import Iterable
from urllib.parse import quote, quote_plus

from maestro import config
from maestro.config import print_to_logfile

# endregion


class Song:
    def __init__(self, song_id: int):
        if song_id < 1:
            raise ValueError("Song ID must be greater than 0.")
        self._song_id = song_id

        self._metadata = None
        self._metadata_changed = False

        self._parsed_lyrics = False
        self._parsed_override_lyrics = False
        self._parsed_translated_lyrics = False

        atexit.register(self._save)

    def reset(self):
        self._metadata = None
        self._metadata_changed = False

        self._parsed_lyrics = False
        self._parsed_override_lyrics = False
        self._parsed_translated_lyrics = False

    def __eq__(self, value):
        if not isinstance(value, type(self)):
            return False
        return value.song_id == self.song_id

    def __hash__(self):
        return hash(self.song_id)

    def __repr__(self):
        return f"Song(ID={self.song_id})"

    @property
    def override_lyrics_path(self):
        return os.path.join(
            config.OVERRIDE_LYRICS_DIR, f"{self.song_title}.lrc"
        )

    @property
    def translated_lyrics_path(self):
        return os.path.join(
            config.TRANSLATED_LYRICS_DIR, f"{self.song_title}.lrc"
        )

    @property
    def song_id(self):
        return self._song_id

    @property
    def song_file(self):
        """e.g. song.mp3"""
        return SONG_DATA[self._song_id]["filename"]

    @property
    def song_path(self):
        """e.g. /path/to/song.mp3"""
        return os.path.join(config.settings["song_directory"], self.song_file)

    @property
    def song_title(self):
        """e.g. 'song'"""
        return os.path.splitext(self.song_file)[0]

    @song_title.setter
    def song_title(self, v):
        old_path = self.song_path
        old_override_lyrics_path = self.override_lyrics_path
        old_translated_lyrics_path = self.translated_lyrics_path

        SONG_DATA[self._song_id]["filename"] = (
            v + os.path.splitext(self.song_file)[1]
        )

        if os.path.exists(old_path):
            os.rename(old_path, self.song_path)
        if os.path.exists(old_override_lyrics_path):
            os.rename(old_override_lyrics_path, self.override_lyrics_path)
        if os.path.exists(old_translated_lyrics_path):
            os.rename(old_translated_lyrics_path, self.translated_lyrics_path)

        self._load_metadata()
        self._metadata["tracktitle"] = v
        self._metadata_changed = True

    @property
    def tags(self) -> set[str]:
        return SONG_DATA[self._song_id]["tags"]

    @tags.setter
    def tags(self, v: set[str]):
        SONG_DATA[self._song_id]["tags"] = v

    @property
    def clips(self) -> dict[str, list[int, int]]:
        return SONG_DATA[self._song_id]["clips"]

    @property
    def set_clip(self) -> str:
        return SONG_DATA[self._song_id]["set-clip"]

    @set_clip.setter
    def set_clip(self, v: str):
        SONG_DATA[self._song_id]["set-clip"] = v

    @property
    def listen_times(self) -> dict[int | str, float]:
        return SONG_DATA[self._song_id]["stats"]

    def _load_metadata(self):
        import music_tag

        self._metadata = music_tag.load_file(self.song_path)

    @property
    def artist(self):
        return self.get_metadata("artist") or "No Artist"

    @artist.setter
    def artist(self, v):
        self.set_metadata("artist", v)

    @property
    def album(self):
        return self.get_metadata("album") or "No Album"

    @album.setter
    def album(self, v):
        self.set_metadata("album", v)

    @property
    def album_artist(self):
        return self.get_metadata("albumartist") or "No Album Artist"

    @album_artist.setter
    def album_artist(self, v):
        self.set_metadata("albumartist", v)

    @property
    def duration(self):
        return self.get_metadata("#length")

    @property
    def artwork(self):
        if self._metadata is None:
            self._load_metadata()
        return (
            self._metadata["artwork"].first
            if "artwork" in self._metadata
            else None
        )

    @property
    def raw_lyrics(self) -> str | None:
        return self.get_metadata("lyrics")

    @raw_lyrics.setter
    def raw_lyrics(self, v):
        if self._metadata is None:
            self._load_metadata()

        if v is None and "lyrics" in self._metadata:
            del self._metadata["lyrics"]
        else:
            self._metadata["lyrics"] = v
        self._parsed_lyrics = False
        self._metadata_changed = True

    @property
    def raw_override_lyrics(self) -> str | None:
        if not os.path.exists(self.override_lyrics_path):
            return None
        with open(self.override_lyrics_path, "r", encoding="utf-8") as f:
            return f.read()

    @raw_override_lyrics.setter
    def raw_override_lyrics(self, v):
        import safer

        if v is None:
            if os.path.exists(self.override_lyrics_path):
                os.remove(self.override_lyrics_path)
        else:
            os.makedirs(config.OVERRIDE_LYRICS_DIR, exist_ok=True)
            with safer.open(
                self.override_lyrics_path, "w", encoding="utf-8"
            ) as f:
                f.write(v)

        self._parsed_override_lyrics = False

    @property
    def raw_translated_lyrics(self) -> str | None:
        if not os.path.exists(self.translated_lyrics_path):
            return None
        with open(self.translated_lyrics_path, "r", encoding="utf-8") as f:
            return f.read()

    @raw_translated_lyrics.setter
    def raw_translated_lyrics(self, v):
        import safer

        if v is None:
            if os.path.exists(self.translated_lyrics_path):
                os.remove(self.translated_lyrics_path)
        else:
            os.makedirs(config.TRANSLATED_LYRICS_DIR, exist_ok=True)
            with safer.open(
                self.translated_lyrics_path, "w", encoding="utf-8"
            ) as f:
                f.write(v)

    def _parse_lyrics(self, raw_lyrics):
        if raw_lyrics is None:
            return None

        raw_lyrics_list = raw_lyrics.splitlines()
        for line in raw_lyrics_list:
            if line and not line.strip().startswith("["):  # not LRC format
                return raw_lyrics_list

        import pylrc

        return pylrc.parse(raw_lyrics) if raw_lyrics else None

    @property
    def parsed_lyrics(self):
        if self._parsed_lyrics is False:
            self._parsed_lyrics = self._parse_lyrics(self.raw_lyrics)
        return self._parsed_lyrics

    @property
    def parsed_override_lyrics(self):
        if self._parsed_override_lyrics is False:
            self._parsed_override_lyrics = self._parse_lyrics(
                self.raw_override_lyrics
            )
        return self._parsed_override_lyrics

    @property
    def parsed_translated_lyrics(self):
        if self._parsed_translated_lyrics is False:
            self._parsed_translated_lyrics = self._parse_lyrics(
                self.raw_translated_lyrics
            )
        return self._parsed_translated_lyrics

    def get_metadata(self, key, resolve=True):
        """
        Get metadata value for `key`.

        If 'resolve' is False, then a MetadataItem is returned instead of the
        resolved value.
        """
        if self._metadata is None:
            self._load_metadata()

        if key not in self._metadata:
            return None
        if resolve:
            return self._metadata[key].value
        return self._metadata[key]

    def set_metadata(self, key, value):
        if self._metadata is None:
            self._load_metadata()

        if key not in config.METADATA_KEYS:
            raise ValueError(f"{key} is not a valid metadata key.")
        if key.startswith("#"):
            raise ValueError(f"{key} is not editable.")

        if key == "tracktitle":
            self.song_title = value  # also change file names
        elif key == "lyrics":
            self.raw_lyrics = value  # unset self._parsed_lyrics
        elif value is None:
            if key in self._metadata:
                del self._metadata[key]
        else:
            self._metadata[key] = value

        self._metadata_changed = True

    def remove_from_data(self):
        del SONG_DATA[self.song_id]

    def _save(self):
        if self._metadata_changed:
            self._metadata.save()


class SongData:
    def __init__(self):
        self.songs = None
        atexit.register(self._save)

    def load(self):
        self.songs = {}
        with open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as f:
            s = f.read()
            if not s:
                return
            d = msgspec.json.decode(s)
            for k, v in d.items():
                self.songs[int(k)] = v

                if "tags" not in v:
                    v["tags"] = set()
                else:
                    v["tags"] = set(v["tags"])

                v["stats_"] = {}
                for year in v["stats"]:
                    if year.isdigit():
                        v["stats_"][int(year)] = v["stats"][year]
                    else:
                        v["stats_"][year] = v["stats"][year]
                v["stats"] = v.pop("stats_")
                if "set-clip" not in v:
                    v["set-clip"] = "default"

    def __getitem__(self, key):
        if self.songs is None:
            self.load()
        return self.songs[key]

    def __setitem__(self, key, value):
        if self.songs is None:
            self.load()
        self.songs[key] = value

    def __delitem__(self, key):
        if self.songs is None:
            self.load()
        del self.songs[key]

    def __iter__(self):
        if self.songs is None:
            self.load()
        return iter(self.songs)

    def items(self):
        if self.songs is None:
            self.load()
        return self.songs.items()

    def values(self):
        if self.songs is None:
            self.load()
        return self.songs.values()

    def _save(self):
        import safer

        if self.songs is not None:
            with safer.open(config.SONGS_INFO_PATH, "wb") as f:
                f.write(msgspec.json.encode(self.songs))

    def add_song(self, filename, tags=None):
        if tags is None:
            tags = set()

        if self.songs is None:
            self.load()
        if not self.songs:
            song_id = 1
        else:
            song_id = max(self) + 1
        self.songs[song_id] = {
            "filename": os.path.split(filename)[1],
            "tags": set(tags),
            "clips": {},
            "stats": {
                config.CUR_YEAR: 0.0,
                "total": 0.0,
            },
            "set-clip": "default",
        }

        song = Song(song_id)
        song.set_metadata("tracktitle", song.song_title)

        return song


SONG_DATA = SongData()


class Songs:
    """
    Wrapper around dict of all `Song` objects.
    """

    def __init__(self):
        self._songs = None
        self._song_data = SONG_DATA

    def load(self):
        self._songs = {Song(k) for k in self._song_data}

    def __contains__(self, value: Song):
        if self._songs is None:
            self.load()
        return value in self._songs

    def __iter__(self) -> Iterable[Song]:
        if self._songs is None:
            self.load()
        return iter(self._songs)

    def __len__(self):
        if self._songs is None:
            self.load()
        return len(self._songs)


SONGS = Songs()


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


def set_timeout(func, timeout, *args, **kwargs):
    def wrapper():
        sleep(timeout)
        func()

    threading.Thread(
        target=wrapper, daemon=True, args=args, kwargs=kwargs
    ).start()


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

    def refresh(self):
        self.resize()


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


class FFmpegProcessHandler:
    def __init__(self, username, password):
        self.process = None
        self.username = username
        self.password = password

    def start(self):
        from spotdl.utils.ffmpeg import get_ffmpeg_path

        self.process = subprocess.Popen(
            # fmt: off
            [
                str(get_ffmpeg_path()),
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
    def __init__(
        self,
        stdscr: "curses._CursesWindow",
        playlist: list[Song],
        clip_mode,
        visualize,
        stream,
        creds,
        want_lyrics,
        want_translated_lyrics,
    ):
        from just_playback import Playback

        self.stdscr = stdscr
        self.scroller = Scroller(
            len(playlist), stdscr.getmaxyx()[0] - 2  # -2 for status bar
        )
        self.playlist = playlist
        self.i = 0
        self._volume = 0
        self.clip_mode = clip_mode
        self.want_discord = False
        self.want_vis = visualize  # want to visualize
        self._want_stream = stream  # want to stream
        self.username, self.password = creds
        self.want_lyrics = want_lyrics
        self.want_translated_lyrics = want_translated_lyrics and want_lyrics

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

        self.discord_connected = 2
        self.discord_rpc = None
        self.discord_last_update = 0
        self.can_update_discord = True  # pypresence installed
        self.discord_updating = False  # lock

        self._librosa = None
        self.can_visualize = True
        self.can_show_visualization = (
            self.want_vis
            # space to show visualization
            and self.screen_height > config.VISUALIZER_HEIGHT + 5
        )

        self.audio_data = None
        self.audio_data = {}  # dict(song_id: (vis data, stream data))
        self.audio_processing_thread = threading.Thread(
            target=self._audio_processing_loop,
            daemon=True,
        )
        self.audio_processing_thread.start()
        self.compiled = None

        self.ffmpeg_process = FFmpegProcessHandler(self.username, self.password)
        if self.want_stream:
            self.ffmpeg_process.start()
        self.break_stream_loop = False
        self.streaming_thread = threading.Thread(
            target=self._streaming_loop,
            daemon=True,
        )
        self.streaming_thread.start()

        self.lyrics: list | None = None
        self.translated_lyrics: list | None = None
        self.lyrics_scroller = Scroller(0, 0)
        self.lyrics_width = 50
        self.lyric_pos = None

        self.show_help = False
        self.help_pos = 0

        self._focus = 0  # 0: queue, 1: lyrics

    def _load_audio(self, path, sr):
        import numpy as np

        # shape = (# channels, # frames)
        audio_data = self._librosa.load(path, mono=False, sr=sr)[0]

        if len(audio_data.shape) == 1:  # mono -> stereo
            audio_data = np.repeat([audio_data], 2, axis=0)
        elif audio_data.shape[0] == 1:  # mono -> stereo
            audio_data = np.repeat(audio_data, 2, axis=0)
        elif audio_data.shape[0] == 6:  # 5.1 -> stereo
            audio_data = np.delete(audio_data, (1, 3, 4, 5), axis=0)

        return audio_data

    def _audio_processing_loop(self):
        import numpy as np

        try:
            from librosa import load, stft, amplitude_to_db

            self._librosa = type(
                "librosa",
                (),
                {
                    "load": staticmethod(load),
                    "stft": staticmethod(stft),
                    "amplitude_to_db": staticmethod(amplitude_to_db),
                },
            )
        except ImportError:
            self.can_visualize = False
            self.can_show_visualization = False
            print_to_logfile(
                "Librosa not installed. Visualization will be disabled."
            )

        while True:
            keys_to_delete = []
            for k in self.audio_data:
                if k not in self.playlist[self.i : self.i + 5]:
                    keys_to_delete.append(k)
            for k in keys_to_delete:
                del self.audio_data[k]

            for i in range(self.i, min(self.i + 5, len(self.playlist))):
                song = self.playlist[i]

                if self.song != song and (
                    self.song not in self.audio_data
                    or (
                        self.want_vis and self.audio_data[self.song][0] is None
                    )
                    or (self.want_stream and self.audio_data[self.song][1] is None)
                ):
                    break
                if song in self.audio_data and (
                    (self.audio_data[song][0] is not None or not self.want_vis)
                    and (
                        self.audio_data[song][1] is not None or not self.want_stream
                    )
                    or self._librosa is None
                ):
                    continue

                song_path = os.path.join(  # NOTE: NOT SAME AS self.song_path
                    config.settings["song_directory"],
                    self.playlist[i].song_file,
                )

                if song not in self.audio_data:
                    self.audio_data[song] = [
                        (
                            self._librosa.amplitude_to_db(
                                np.abs(
                                    self._librosa.stft(
                                        self._load_audio(
                                            song_path,
                                            sr=config.VIS_SAMPLE_RATE,
                                        )
                                    )
                                ),
                                ref=np.max,
                            )
                            + 80
                            if self.want_vis and self.can_visualize
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
                            if self.want_stream
                            else None
                        ),
                    ]
                else:
                    if (
                        self.audio_data[song][0] is None
                        and self.want_vis
                        and self.can_visualize
                    ):
                        self.audio_data[song][0] = (
                            self._librosa.amplitude_to_db(
                                np.abs(
                                    self._librosa.stft(
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
                    if self.audio_data[song][1] is None and self.want_stream:
                        self.audio_data[song][1] = np.int16(
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
                self.want_stream
                and self.username is not None
                and self.audio_data is not None
                and self.song in self.audio_data
                and self.audio_data[self.song][1] is not None
                and self.playback is not None
                # is 0 for a while after resuming, and is -1 if playback is
                # inactive or file is not loaded
                and self.playback.curr_pos > 0
            ):
                for fpos in range(
                    int(self.playback.curr_pos * config.STREAM_SAMPLE_RATE),
                    self.audio_data[self.song][1].shape[1],
                    config.STREAM_CHUNK_SIZE,
                ):
                    try:
                        # print_to_logfile(
                        #     self.song_id,
                        #     fpos / config.STREAM_SAMPLE_RATE,
                        #     self.playback.curr_pos,
                        # )  # DEBUG
                        self.ffmpeg_process.write(
                            self.audio_data[self.song][1][
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
        if self.want_stream:
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
    def want_stream(self):
        return self._want_stream

    @want_stream.setter
    def want_stream(self, value):
        if self._librosa is None:
            value = False
        self._want_stream = value

    @property
    def song(self):
        return self.playlist[self.i]

    @property
    def song_id(self):
        return self.song.song_id

    @property
    def song_file(self):
        return self.song.song_file

    @property
    def song_path(self):
        return self.song.song_path

    @property
    def song_title(self):
        return self.song.song_title

    @property
    def song_artist(self):
        return self.song.artist

    @property
    def song_album(self):
        return self.song.album

    @property
    def album_artist(self):
        return self.song.album_artist

    @property
    def artwork(self):
        return (
            self.song.artwork.raw_thumbnail([1024, 1024])
            if self.song.artwork
            else None
        )

    @property
    def screen_height(self):
        return self.stdscr.getmaxyx()[0]

    @property
    def screen_width(self):
        return self.stdscr.getmaxyx()[1]

    @property
    def can_show_lyrics(self):
        return self.want_lyrics and self.lyrics is not None

    @property
    def can_show_translated_lyrics(self):
        return (
            self.want_translated_lyrics and self.translated_lyrics is not None
        )

    @property
    def focus(self):
        return self._focus if self.can_show_lyrics else 0

    @focus.setter
    def focus(self, value):
        self._focus = value if self.can_show_lyrics else 0

    # endregion

    def seek(self, pos):
        if self.playback is not None:
            pos = max(0, pos)
            self.playback.seek(pos)
            self.break_stream_loop = True
            if self.can_mac_now_playing and self.mac_now_playing is not None:
                self.mac_now_playing.pos = round(pos)
                self.update_now_playing = True
            self.last_timestamp = pos

    def scroll_forward(self):
        if self.show_help:
            self.help_pos += 1
        elif self.focus == 1:
            if self.lyric_pos is None:
                self.lyric_pos = self.lyrics_scroller.pos
            self.lyric_pos = min(self.lyric_pos + 1, len(self.lyrics) - 1)
        elif self.focus == 0:
            self.scroller.scroll_forward()

    def scroll_backward(self):
        if self.show_help:
            self.help_pos -= 1
        elif self.focus == 1:
            if self.lyric_pos is None:
                self.lyric_pos = self.lyrics_scroller.pos
            self.lyric_pos = max(self.lyric_pos - 1, 0)
        elif self.focus == 0:
            self.scroller.scroll_backward()

    def snap_back(self):
        if self.focus == 1:
            self.lyric_pos = None
        elif self.focus == 0:
            self.scroller.pos = self.i
            self.scroller.refresh()

    def set_volume(self, v):
        """Set volume w/o changing self.volume."""
        self.playback.set_volume(v / 100)

    def quit(self):
        if self.ffmpeg_process is not None:
            self.ffmpeg_process.terminate()
        if self.discord_rpc is not None:
            self.discord_rpc.close()

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

    def connect_to_discord(self):
        try:
            from pypresence import Client as DiscordRPCClient
        except ImportError:
            print_to_logfile(
                "pypresence not installed. Discord presence will be disabled."
            )
            self.can_update_discord = False
        discord_rpc = DiscordRPCClient(client_id=config.DISCORD_ID)
        discord_rpc.start()
        return discord_rpc

    def update_discord_metadata(self):
        if self.discord_updating:
            return
        if self.can_update_discord and self.want_discord:
            self.discord_updating = True

            t = time()
            if self.discord_last_update + 15 > t:
                sleep(15 - (t - self.discord_last_update))
            song_name, artist_name, album_name = "", "", ""

            # minimum 2 characters (Discord requirement)
            new_song_name = self.song_title.ljust(2)
            new_artist_name = "by " + self.song_artist.ljust(2)
            new_album_name = self.song_album.ljust(2)

            if (
                new_song_name != song_name
                or new_artist_name != artist_name
                or new_album_name != album_name
            ):
                song_name = new_song_name
                artist_name = new_artist_name
                album_name = new_album_name

                d = dict(
                    details=song_name,
                    state=artist_name,
                    large_image=(
                        f"{config.IMAGE_URL}/{self.username}?_={time()}"
                        if self.username
                        else "maestro-icon"
                    ),
                    small_image="maestro-icon-small",
                    large_text=album_name,
                    buttons=(
                        [
                            {
                                "label": "Listen Along",
                                "url": f"{config.MAESTRO_SITE}/listen-along/{self.username}",
                            }
                        ]
                        if self.username and self.want_stream
                        else None
                    ),
                )
                d = {k: v for k, v in d.items() if v is not None}

                try:
                    self.discord_rpc.set_activity(**d)
                    self.discord_last_update = time()
                except Exception as e:  # pylint: disable=bare-except
                    print_to_logfile("Discord update error:", e)
                    song_name, artist_name, album_name = "", "", ""
                    self.discord_connected = 2
                    try:
                        self.discord_rpc = self.connect_to_discord()
                        self.discord_connected = 1
                        self.discord_updating = False
                        self.update_discord_metadata()
                    except Exception as err:
                        print_to_logfile("Discord connection error:", err)
                        self.discord_connected = 0
                finally:
                    self.discord_updating = False

    def update_mac_now_playing_metadata(self):
        from maestro.icon import img as default_artwork

        if self.can_mac_now_playing:
            self.mac_now_playing.paused = False
            self.mac_now_playing.pos = 0
            self.mac_now_playing.length = self.duration
            self.mac_now_playing.cover = (
                self.artwork if self.artwork else default_artwork
            )

            multiprocessing_put_word(
                self.mac_now_playing.title_queue,
                self.song_title,
            )
            multiprocessing_put_word(
                self.mac_now_playing.artist_queue,
                self.song_artist,
            )

            self.update_now_playing = True

    def update_icecast_metadata(self):
        import requests

        return requests.post(
            config.UPDATE_METADATA_URL,
            data={
                "mount": self.username,
                "song": quote_plus(self.song_title),
                "artist": quote_plus(self.song_artist),
                "album": quote_plus(self.song_album),
                "albumartist": quote_plus(self.album_artist),
                "paused": int(self.paused),
            },
            auth=(self.username, self.password),
            timeout=5,
        )

    def icecast_metadata_update_loop(self):
        success = False
        last_metadata_update_attempt = 0
        while not success:
            t = time()
            if t - last_metadata_update_attempt > 5:
                try:
                    response = self.update_icecast_metadata()
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
            target=self.icecast_metadata_update_loop, daemon=True
        ).start()

    def update_stream_metadata(self):  # artwork + icecast metadata
        import requests

        self.break_stream_loop = True
        if self.discord_connected or self.want_stream:
            if not requests.post(
                config.UPDATE_ARTWORK_URL,
                params={"mount": self.username},
                files={"artwork": self.artwork},
                auth=(self.username, self.password),
                timeout=5,
            ).ok:
                print_to_logfile("Failed to update artwork.")

        if self.want_stream:
            self.threaded_update_icecast_metadata()

    def update_metadata(self):
        def f():
            self.update_mac_now_playing_metadata()
            self.update_stream_metadata()
            self.update_discord_metadata()

        threading.Thread(target=f, daemon=True).start()

    def initialize_discord(self):
        self.want_discord = True
        try:
            self.discord_rpc = self.connect_to_discord()
            self.discord_connected = 1
        except Exception as e:  # pylint: disable=broad-except,unused-variable
            self.discord_connected = 0
            print_to_logfile("Discord connection error:", e)

    def threaded_initialize_discord(self):
        threading.Thread(target=self.initialize_discord, daemon=True).start()

    def output(self, pos):
        from maestro.jit_funcs import render

        screen_height = self.screen_height
        if self.want_lyrics:
            screen_width = self.screen_width - self.lyrics_width
        else:
            screen_width = self.screen_width

        self.can_show_visualization = (
            self.want_vis
            and self.can_visualize
            and screen_height > config.VISUALIZER_HEIGHT + 5
        )
        self.scroller.resize(
            screen_height
            - 3  # -3 for status bar
            - 1  # -1 for header
            - (self.prompting != None)  # - add mode
            # - visualizer
            - (config.VISUALIZER_HEIGHT if self.can_show_visualization else 0)
        )

        if self.clip_mode:
            pos -= self.clip[0]

        self.stdscr.erase()

        length_so_far = 0
        if self.want_discord:
            if self.discord_connected == 2:
                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    "Connecting to Discord ... ",
                    screen_width,
                    length_so_far,
                    curses.color_pair(12),
                )
            elif self.discord_connected == 1:
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
        if self.want_vis:
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
            elif self.song not in self.audio_data:
                visualize_message = "Loading visualization..."
                visualize_color = 12
            elif not self.compiled:
                visualize_message = "Compiling renderer..."
                visualize_color = 12

        if self.want_stream:
            prefix = "  " if self.want_discord else ""
            if self.username:
                long_stream_message = (
                    prefix
                    + f"Streaming at {config.MAESTRO_SITE}/listen-along/{self.username}"
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
        longest_song_id_length = max(
            len(str(song.song_id)) for song in self.playlist
        )

        for j in range(
            self.scroller.top, self.scroller.top + self.scroller.win_size
        ):
            if j <= len(self.playlist) - 1:
                length_so_far = 0

                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    " "
                    * (
                        longest_song_id_length
                        - len(str(self.playlist[j].song_id))
                    )
                    + f"{self.playlist[j].song_id} ",
                    screen_width,
                    length_so_far,
                    curses.color_pair(2),
                )
                if j == self.i:
                    length_so_far = addstr_fit_to_width(
                        self.stdscr,
                        f"{self.playlist[j].song_title} ",
                        screen_width,
                        length_so_far,
                        curses.color_pair(song_display_color) | curses.A_BOLD,
                    )
                else:
                    length_so_far = addstr_fit_to_width(
                        self.stdscr,
                        f"{self.playlist[j].song_title} ",
                        screen_width,
                        length_so_far,
                        (
                            curses.color_pair(4)
                            if (j == self.scroller.pos)
                            else curses.A_NORMAL
                        ),
                    )
                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    f"{', '.join(self.playlist[j].tags)}",
                    screen_width,
                    length_so_far,
                    curses.color_pair(2),
                )
            self.stdscr.move((j - self.scroller.top) + 2, 0)

        if self.prompting is not None:
            # pylint: disable=unsubscriptable-object
            if self.prompting[2] == config.PROMPT_MODES["tag"]:
                adding_song_length = addstr_fit_to_width(
                    self.stdscr,
                    "Add tag(s) to songs: " + self.prompting[0],
                    screen_width,
                    0,
                )
            else:
                adding_song_length = addstr_fit_to_width(
                    self.stdscr,
                    config.PROMPT_MODES_LIST[self.prompting[2]].capitalize()
                    + " song: "
                    + self.prompting[0],
                    screen_width,
                    0,
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
            f"{self.song_title} ",
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
            screen_height
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
            screen_height
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
                screen_height
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
                screen_height
                - (
                    config.VISUALIZER_HEIGHT
                    if self.can_show_visualization
                    else 0
                ),
                0,
            )
            if (
                self.song not in self.audio_data
                or self.audio_data[self.song][0] is None
            ):
                self.stdscr.addstr(
                    (
                        (" " * (screen_width - 1) + "\n")
                        * config.VISUALIZER_HEIGHT
                    ).rstrip()
                )
            elif not self.compiled:
                if self.compiled is None:
                    self.compiled = False

                    def thread_func():
                        vdata = self.audio_data[self.song][0]
                        render(
                            screen_width,
                            vdata,
                            min(round(pos * config.FPS), vdata.shape[2] - 1),
                            config.VISUALIZER_HEIGHT,
                        )
                        self.compiled = True

                    threading.Thread(target=thread_func, daemon=True).start()
                self.stdscr.addstr(
                    (
                        (" " * (screen_width - 1) + "\n")
                        * config.VISUALIZER_HEIGHT
                    ).rstrip()
                )
            elif self.compiled:
                vdata = self.audio_data[self.song][0]
                rendered_lines = render(
                    screen_width,
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

        if self.can_show_lyrics:
            from grapheme import graphemes

            # self.stdscr.redrawwin()  # workaround for foreign characters

            num_lines = min(
                len(self.lyrics),
                (
                    screen_height // 2
                    if self.can_show_translated_lyrics
                    else screen_height - 1
                ),
            )

            cur_lyric_i = None
            is_timed = is_timed_lyrics(self.lyrics)
            if is_timed:
                for i, lyric in enumerate(self.lyrics):
                    if lyric.time > pos:
                        cur_lyric_i = i - 1
                        break
                if cur_lyric_i is None:
                    cur_lyric_i = len(self.lyrics) - 1
            self.lyrics_scroller.pos = (
                self.lyric_pos or cur_lyric_i or self.lyrics_scroller.pos
            )
            self.lyrics_scroller.resize(num_lines)
            if not is_timed:
                self.lyrics_scroller.pos = min(
                    max(
                        self.lyrics_scroller.win_size // 2,
                        self.lyrics_scroller.pos,
                    ),
                    self.lyrics_scroller.num_lines
                    - self.lyrics_scroller.win_size // 2,
                )

            self.stdscr.move(0, screen_width)
            lyric_focus_msg = (
                f"Focus: {'lyrics' if self.focus == 1 else 'queue'}"
            )
            addstr_fit_to_width(
                self.stdscr,
                " " * (self.lyrics_width - len(lyric_focus_msg))
                + lyric_focus_msg,
                self.lyrics_width,
                0,
                curses.color_pair(19),
            )

            for i in range(
                self.lyrics_scroller.top, self.lyrics_scroller.top + num_lines
            ):
                vertical_pos = (i - self.lyrics_scroller.top) * (
                    2 if self.can_show_translated_lyrics else 1
                ) + 1

                style = curses.color_pair(9)
                # pylint: disable=unsubscriptable-object
                lyric_text = get_lyric(self.lyrics[i]).strip()
                if cur_lyric_i is not None:
                    if i == cur_lyric_i:
                        style = curses.color_pair(9) | curses.A_BOLD

                        self.stdscr.move(
                            vertical_pos,
                            screen_width + config.LYRIC_PADDING - 2,
                        )
                        self.stdscr.addstr("> ", style)
                    elif i == self.lyric_pos:
                        style = curses.color_pair(4)

                        self.stdscr.move(
                            vertical_pos,
                            screen_width + config.LYRIC_PADDING - 2,
                        )
                        self.stdscr.addstr("> ", style)
                    elif i < cur_lyric_i:
                        style = curses.color_pair(9) | curses.A_DIM

                try:
                    width = 0
                    for g in graphemes(lyric_text):
                        width += 1
                        # NOTE: why -1? No one knows.
                        if width < self.lyrics_width - config.LYRIC_PADDING:
                            self.stdscr.move(
                                vertical_pos,
                                screen_width + config.LYRIC_PADDING + width - 1,
                            )
                            self.stdscr.addstr(g, style)
                        else:
                            break
                except curses.error:  # bottom right corner errors
                    break

                if (
                    self.can_show_translated_lyrics
                    and i < len(self.translated_lyrics)
                    and self.stdscr.getyx()[0] < screen_height
                ):
                    style = curses.A_DIM
                    if i == cur_lyric_i:
                        style |= curses.A_BOLD
                    elif i == self.lyric_pos and is_timed:
                        style |= curses.color_pair(4)

                    try:
                        width = 0
                        for g in graphemes(
                            get_lyric(self.translated_lyrics[i]).strip()
                        ):
                            width += 1
                            if (
                                width
                                < self.lyrics_width - config.LYRIC_PADDING - 1
                            ):
                                self.stdscr.move(
                                    vertical_pos + 1,
                                    screen_width
                                    + config.LYRIC_PADDING
                                    + 1
                                    + width
                                    - 1,
                                )
                                self.stdscr.addstr(g, style)
                            else:
                                break
                    except curses.error:  # bottom right corner errors
                        break
        elif self.want_lyrics:
            self.stdscr.move(0, screen_width + config.LYRIC_PADDING)
            addstr_fit_to_width(
                self.stdscr,
                "No lyrics found.",
                self.lyrics_width - config.LYRIC_PADDING,
                0,
                curses.color_pair(4),
            )

        if self.show_help:
            l = 15
            r = self.screen_width - l
            t = 5
            b = self.screen_height - t

            if l < r and t < b:
                # draw border
                self.stdscr.addch(t, l, curses.ACS_ULCORNER)
                self.stdscr.addch(t, r, curses.ACS_URCORNER)
                self.stdscr.addch(b, l, curses.ACS_LLCORNER)
                self.stdscr.addch(b, r, curses.ACS_LRCORNER)
                for x in range(l + 1, r):
                    self.stdscr.addch(t, x, curses.ACS_HLINE)
                    self.stdscr.addch(b, x, curses.ACS_HLINE)
                for y in range(t + 1, b):
                    self.stdscr.addch(y, l, curses.ACS_VLINE)
                    self.stdscr.addch(y, r, curses.ACS_VLINE)

                # draw text
                self.stdscr.move(t + 1, l + 1)
                i = max(
                    0,
                    min(self.help_pos, len(config.PLAY_CONTROLS) - (b - t - 1)),
                )
                while self.stdscr.getyx()[0] < b:
                    if i < len(config.PLAY_CONTROLS):
                        key, desc = config.PLAY_CONTROLS[i]
                        length_so_far = addstr_fit_to_width(
                            self.stdscr,
                            key
                            + " " * (config.INDENT_CONTROL_DESC - len(key))
                            + " ",
                            r - l - 1,
                            0,
                            curses.color_pair(18) | curses.A_BOLD,
                        )
                        length_so_far = addstr_fit_to_width(
                            self.stdscr,
                            desc
                            + " " * (r - l - 1 - length_so_far - len(desc)),
                            r - l - 1,
                            length_so_far,
                            curses.color_pair(18),
                        )
                        i += 1
                        self.stdscr.move(self.stdscr.getyx()[0] + 1, l + 1)
                    else:
                        self.stdscr.addstr(" " * (r - l - 1))

        if self.prompting is not None:
            # pylint: disable=unsubscriptable-object
            self.stdscr.move(
                screen_height
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
    curses.init_pair(9, curses.COLOR_CYAN, -1)

    curses.init_pair(11, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(12, curses.COLOR_BLACK + 8, curses.COLOR_BLACK)
    curses.init_pair(13, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(14, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(15, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(16, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(17, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
    curses.init_pair(18, -1, curses.COLOR_BLACK)
    curses.init_pair(19, curses.COLOR_CYAN, curses.COLOR_BLACK)
    # endregion

    curses.curs_set(False)
    stdscr.nodelay(True)
    try:
        curses.set_escdelay(25)  # 25 ms
    except:  # pylint: disable=bare-except
        pass


class SongParamType(click.ParamType):
    name = "song"

    def convert(self, value, param, ctx) -> Song:
        if value.isdecimal():
            value = int(value)

        if type(value) == int:
            song = Song(value)
            if song in SONGS:
                return song
            self.fail(f"No song found with ID {value}.", param, ctx)

        if not value.isdecimal():
            results = search_song(value)
            if not any(results):
                self.fail(f"No song found matching '{value}'.", param, ctx)

            for result in results:
                if len(result) == 1:
                    return result[0]
                if len(result) > 1:
                    break

            if param is not None:  # called by click
                for song in sum(results, []):
                    print_entry(song, value)
            self.fail("Multiple songs found", param, ctx)

        self.fail("Invalid song argument", param, ctx)


CLICK_SONG = SongParamType()


def yt_embed_artwork(yt_dlp_info):
    import music_tag
    import requests

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


def clip_editor(stdscr, song: Song, name, start=None, end=None):
    from just_playback import Playback

    playback = Playback()
    playback.load_file(song.song_path)

    init_curses(stdscr)

    if name in song.clips:
        clip_start, clip_end = song.clips[name]
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
                song,
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
    song: Song,
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

    stdscr.move(stdscr.getyx()[0] + 1, 0)  # 1-line spacing

    # region pause indicator, song ID+title, tags
    length_so_far = 0
    length_so_far = addstr_fit_to_width(
        stdscr,
        ("| " if paused else "> ") + f"({song.song_id}) ",
        screen_width,
        length_so_far,
        curses.color_pair(3),
    )
    length_so_far = addstr_fit_to_width(
        stdscr,
        f"{song.song_title} ",
        screen_width,
        length_so_far,
        curses.color_pair(3) | curses.A_BOLD,
    )
    length_so_far = addstr_fit_to_width(
        stdscr,
        f"{', '.join(song.tags)} ",
        screen_width,
        length_so_far,
        curses.color_pair(2),
    )
    stdscr.move(stdscr.getyx()[0] + 1, 0)
    # endregion

    # region credits
    length_so_far = 0
    length_so_far = addstr_fit_to_width(
        stdscr,
        f"{song.artist} - ",
        screen_width,
        length_so_far,
        curses.color_pair(2),
    )
    try:
        length_so_far = addstr_fit_to_width(
            stdscr,
            song.album,
            screen_width,
            length_so_far,
            curses.color_pair(2) | curses.A_ITALIC,
        )
    except:  # pylint: disable=bare-except
        print_to_logfile("Failed to italicize text in curses.")
        length_so_far = addstr_fit_to_width(
            stdscr,
            song.album,
            screen_width,
            length_so_far,
            curses.color_pair(2),
        )
    addstr_fit_to_width(
        stdscr,
        f" ({song.album_artist})",
        screen_width,
        length_so_far,
        curses.color_pair(2),
    )
    stdscr.move(stdscr.getyx()[0] + 1, 0)
    # endregion

    stdscr.move(stdscr.getyx()[0] + 1, 0)  # 1-line spacing

    # region controls
    controls = [
        ("t", "toggle between editing the start and end of the clip"),
        (
            "LEFT/RIGHT",
            "move whichever clip end you are editing by 0.1 seconds",
        ),
        (
            "SHIFT+LEFT/RIGHT",
            "move whichever clip end you are editing by 1 second",
        ),
        ("SPACE", "play/pause"),
        ("ENTER", "exit the editor and save the clip"),
        ("q", "exit the editor without saving the clip"),
    ]
    for control in controls:
        length_so_far = 0
        length_so_far = addstr_fit_to_width(
            stdscr,
            f"{control[0]}: ",
            screen_width,
            length_so_far,
            curses.A_BOLD,
        )
        length_so_far = addstr_fit_to_width(
            stdscr,
            f"{control[1]}",
            screen_width,
            length_so_far,
        )
        stdscr.move(stdscr.getyx()[0] + 1, 0)
    # endregion

    stdscr.refresh()


def get_username():
    import keyring

    return keyring.get_password("maestro-music", "username")


def get_password():
    import keyring

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

    import requests

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

    import keyring

    current_username = keyring.get_password("maestro-music", "username")
    if current_username == username:
        click.secho(f"User '{username}' is already logged in.", fg="yellow")
        return
    if current_username is not None:
        click.secho(
            f"Logging in as user '{username}' will log out current user '{current_username}'.",
            fg="yellow",
        )

    import requests

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


def search_song(phrase):
    """
    CASE INSENSITIVE. Returns a tuple of three lists:
    0: songs that match the phrase exactly
    1: songs that start with the phrase
    1: songs that contain the phrase but do not start with it
    """
    phrase = phrase.lower()

    results = [], [], []  # is, starts, contains but does not start
    for song in SONGS:
        song_title = song.song_title.lower()
        if song_title == phrase:
            results[0].append(song)
        elif song_title.startswith(phrase):
            results[1].append(song)
        elif phrase in song_title:
            results[2].append(song)

    return results


def print_entry(
    song: Song, highlight: str | None = None, year: int | str | None = None
):
    """
    Pretty prints ([] means optional)
        <song ID> <song name> <total duration> <seconds listened> <times listened> <clip> <tags>
            [<artist> - <album> (<album artist>)]

    highlight: a string to highlight (the first occurrence of) in the song name
    """
    click.secho(f"{song.song_id} ", fg="bright_black", nl=False)
    if highlight is None:
        click.secho(song.song_title + " ", fg="blue", nl=False, bold=True)
    else:
        highlight_loc = song.song_title.lower().find(highlight.lower())
        click.secho(
            song.song_title[:highlight_loc],
            fg="blue",
            nl=False,
            bold=True,
        )
        click.secho(
            song.song_title[highlight_loc : highlight_loc + len(highlight)],
            fg="yellow",
            nl=False,
            bold=True,
        )
        click.secho(
            song.song_title[highlight_loc + len(highlight) :] + " ",
            fg="blue",
            nl=False,
            bold=True,
        )

    click.secho(
        format_seconds(
            song.duration,
            show_decimal=True,
            digital=False,
        )
        + " ",
        nl=False,
    )
    if year is not None:
        click.secho(
            format_seconds(
                song.listen_times[year],
                show_decimal=True,
                digital=False,
            )
            + " ",
            fg="yellow",
            nl=False,
        )
        click.secho(
            f"{song.listen_times[year] / song.duration:0.2f} ",
            fg="green",
            nl=False,
        )

    if song.set_clip in song.clips:
        start, end = map(
            lambda f: format_seconds(f, show_decimal=True),
            song.clips[song.set_clip],
        )
        click.secho(
            f"[{start}, {end}] ",
            fg="magenta",
            nl=False,
        )

    click.secho(", ".join(song.tags), fg="bright_black")

    click.secho(
        f"{(len(str(song.song_id))+1)*' '}{song.artist if song.artist else 'No Artist'} - ",
        fg="bright_black",
        nl=False,
    )
    click.secho(
        (song.album if song.album else "No Album"),
        italic=True,
        fg="bright_black",
        nl=False,
    )
    click.secho(
        f" ({song.album_artist if song.album_artist else 'No Album Artist'})",
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


def is_timed_lyrics(lyrics):
    from pylrc.classes import Lyrics

    return isinstance(lyrics, Lyrics)


def get_lyric(lyric_obj):
    if isinstance(lyric_obj, str):
        return lyric_obj
    return lyric_obj.text  # pylrc.classes.LyricLine


def set_lyric(lyrics, i, val):
    if isinstance(lyrics[i], str):
        lyrics[i] = val
    else:
        lyrics[i].text = val


def display_lyrics(lyrics, song, prefix: str = ""):
    if prefix:
        prefix += " "

    if lyrics is None:
        click.secho(
            f'No {prefix}lyrics found for "{song.song_title}" (ID: {song.song_id}).',
            fg="red",
        )
        return

    if prefix:
        prefix = prefix.capitalize() + "l"
    else:
        prefix = "L"

    click.echo(f"{prefix.capitalize()}yrics for ", nl=False)
    click.secho(song.song_title, fg="blue", bold=True, nl=False)
    click.echo(f" (ID {song.song_id}):")

    if is_timed_lyrics(lyrics):
        for lyric in lyrics:
            click.echo(
                f"\t[{format_seconds(lyric.time, show_decimal=True)}] {lyric.text}"
            )
    else:
        click.echo("\n".join([f"\t{lyric}" for lyric in lyrics]))


def filter_songs(
    tags: set[str],
    exclude_tags,
    artists,
    albums,
    album_artists,
    match_all,
    combine_artists,
):
    songs = []
    for song in SONGS:
        search_criteria = (
            (
                (
                    any(
                        artist.lower()
                        in song.artist.lower()
                        + (
                            f", {song.album_artist.lower()}"
                            if combine_artists
                            else ""
                        )
                        for artist in artists
                    )
                ),
                artists,
            ),
            (
                (any(album.lower() in song.album.lower() for album in albums)),
                albums,
            ),
            (
                (
                    any(
                        album_artist.lower()
                        in song.album_artist.lower()
                        + (
                            f", {song.artist.lower()}"
                            if combine_artists
                            else ""
                        )
                        for album_artist in album_artists
                    )
                ),
                album_artists,
            ),
        )
        search_criteria = tuple(
            c[0] for c in filter(lambda t: t[1], search_criteria)
        )

        if match_all:
            if not search_criteria:
                search_criteria = (True,)

            search_criteria = all(search_criteria) and (
                not tags or (tags <= song.tags)  # subset
            )
        elif any(search_criteria):
            search_criteria = True
        elif tags:
            search_criteria = tags & song.tags
        else:
            search_criteria = not search_criteria

        if search_criteria and not exclude_tags & song.tags:
            songs.append(song)

    return songs
