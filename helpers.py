# region imports
import curses
import logging
import multiprocessing
import os
import threading
import warnings

logging.disable(logging.INFO)

import click
import numpy as np

from shutil import copy, move
from datetime import date

from numba import jit  # NOTE: I think I'm in love with this decorator
from numba.core.errors import NumbaWarning

warnings.simplefilter("ignore", category=NumbaWarning)
# endregion

# region constants

DISCORD_ID = 1039038199881810040

CUR_YEAR = date.today().year
EXTS = (".mp3", ".wav", ".flac", ".ogg")

# region paths
MAESTRO_DIR = os.path.join(os.path.expanduser("~"), ".maestro-files/")

SONGS_DIR = os.path.join(MAESTRO_DIR, "songs/")

SONGS_INFO_PATH = os.path.join(MAESTRO_DIR, "songs.txt")

STATS_DIR = os.path.join(MAESTRO_DIR, "stats/")
CUR_YEAR_STATS_PATH = os.path.join(STATS_DIR, f"{CUR_YEAR}.txt")
TOTAL_STATS_PATH = os.path.join(STATS_DIR, "total.txt")

FREQ_CACHE_DIR = os.path.join(MAESTRO_DIR, "cache/freqs/")
DATA_CACHE_DIR = os.path.join(MAESTRO_DIR, "cache/data")
# endregion

# region player
HORIZONTAL_BLOCKS = {
    1: "▏",
    2: "▎",
    3: "▍",
    4: "▌",
    5: "▋",
    6: "▊",
    7: "▉",
    8: "█",
}
SCRUB_TIME = 5  # in seconds
VOLUME_STEP = 0.01  # self.volume is 0-1
MIN_PROGRESS_BAR_WIDTH = 20
MIN_VOLUME_BAR_WIDTH, MAX_VOLUME_BAR_WIDTH = 10, 40
# endregion

# region visualizer
FPS = 60

STEP_SIZE = 512  # librosa default
SAMPLE_RATE = STEP_SIZE * FPS

VERTICAL_BLOCKS = {
    0: " ",
    1: "▁",
    2: "▂",
    3: "▃",
    4: "▄",
    5: "▅",
    6: "▆",
    7: "▇",
    8: "█",
}
VISUALIZER_HEIGHT = 8  # should divide 80

FLATTEN_FACTOR = 3  # higher = more flattening; 1 = no flattening
# endregion

# endregion


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
        return self.top + self.win_size // 2

    def resize(self, win_size):
        self.win_size = win_size
        self.top = max(0, self.pos - self.win_size // 2)
        self.top = max(0, min(self.num_lines - self.win_size, self.top))


def fit_string_to_width(string, width, length_so_far):
    if length_so_far + len(string) > width:
        remaining_width = width - length_so_far
        if remaining_width >= 3:
            string = string[: (remaining_width - 3)] + "..."
        else:
            string = "." * remaining_width
    length_so_far += len(string)
    return string, length_so_far


def addstr_fit_to_width(stdscr, string, width, length_so_far, *args, **kwargs):
    string, length_so_far = fit_string_to_width(string, width, length_so_far)
    if string:
        stdscr.addstr(string, *args, **kwargs)
    return length_so_far


@jit
def lerp(start, stop, t):
    return start + t * (stop - start)


@jit
def bin_average(arr, n, include_remainder=False):
    remainder = arr.shape[1] % n
    if remainder == 0:
        return np.max(arr.reshape(arr.shape[0], -1, n), axis=1)

    avg_head = np.max(arr[:, :-remainder].reshape(arr.shape[0], -1, n), axis=1)
    if include_remainder:
        avg_tail = np.max(
            arr[:, -remainder:].reshape(arr.shape[0], -1, remainder), axis=1
        )
        return np.concatenate((avg_head, avg_tail), axis=1)

    return avg_head


# @jit
def render(num_bins, freqs, t, mono=None):
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

    if mono:
        freqs[0, :, t] = (freqs[0, :, t] + freqs[1, :, t]) / 2

    num_vertical_block_sizes = len(VERTICAL_BLOCKS) - 1
    freqs = np.round(
        bin_average(
            freqs[:, :, t],
            num_bins,
            (freqs.shape[-2] % num_bins) > num_bins / 2,
        )
        / 80
        * VISUALIZER_HEIGHT
        * num_vertical_block_sizes
    )

    res = ""
    arr = np.zeros((int(not mono) + 1, VISUALIZER_HEIGHT, num_bins))
    for b in range(num_bins):
        # NOTE: only l for now
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

    for h in range(VISUALIZER_HEIGHT - 1, -1, -1):
        for b in range(num_bins):
            res += VERTICAL_BLOCKS[arr[0, h, b]]
        if not mono:
            res += " " * gap_bins
            for b in range(num_bins):
                res += VERTICAL_BLOCKS[arr[1, h, b]]
        res += "\n"

    return res.rstrip()


class AudioData:
    def __init__(self, song_path=None, freqs=True, data=True):
        if song_path is None:
            self.data = self.freqs = None
            self.loaded_song = ""
            self.loading = False
            return

        try:
            self.loading = True

            if data:
                self.load_data(song_path)

            if freqs:
                self.load_freqs(song_path)
                self.freqs = 80 * (self.freqs / 80) ** FLATTEN_FACTOR  # flatten

            self.loaded_song = song_path
            self.loading = False
        except:  # pylint: disable=bare-except
            self.data = self.freqs = self.loaded_song = self.loading = None

    def load_data(self, song_path):
        data_cache_path = os.path.join(
            DATA_CACHE_DIR,
            os.path.splitext(os.path.basename(song_path))[0] + ".npy",
        )

        if not os.path.exists(data_cache_path):
            from librosa import load

            self.data = load(song_path, mono=False, sr=SAMPLE_RATE)[0]

            if len(self.data.shape) == 1:  # mono -> stereo
                self.data = np.repeat([self.data], 2, axis=0)
            elif self.data.shape[0] == 1:  # mono -> stereo
                self.data = np.repeat(self.data, 2, axis=0)
            elif self.data.shape[0] == 6:  # 5.1 surround -> stereo
                self.data = np.delete(self.data, (1, 3, 4, 5), axis=0)
            np.save(data_cache_path, self.data)
        else:
            self.data = np.load(data_cache_path)

    def load_freqs(self, song_path):
        freq_cache_path = os.path.join(
            FREQ_CACHE_DIR,
            os.path.splitext(os.path.basename(song_path))[0] + ".npy",
        )

        if not os.path.exists(freq_cache_path):
            from librosa import stft, amplitude_to_db

            self.load_data(song_path)

            self.freqs = (
                amplitude_to_db(np.abs(stft(self.data)), ref=np.max) + 80
            )  # [-80, 0] -> [0, 80]
            np.save(freq_cache_path, self.freqs)
        else:
            self.freqs = np.load(freq_cache_path)


class PlayerOutput:
    def __init__(
        self, stdscr, playlist, volume, clip_mode, update_discord, visualize
    ):
        self.stdscr = stdscr
        self.scroller = Scroller(
            len(playlist), stdscr.getmaxyx()[0] - 2  # -2 for status bar
        )
        self.playlist = playlist
        self.volume = volume
        self.clip_mode = clip_mode
        self.update_discord = update_discord
        self.can_visualize = self.visualize = visualize

        self.i = 0
        self.looping_current_song = False
        self.duration = 0
        self.paused = False
        self.ending = False
        self.adding_song: None | tuple = None
        self.clip = (0, 0)
        self.discord_connected = multiprocessing.Value("i", 2)
        self.visualizer_data = AudioData()

    @property
    def song_path(self):
        return os.path.join(SONGS_DIR, self.playlist[self.i][1])

    def output(self, pos):
        self.can_visualize = (
            self.visualize and self.stdscr.getmaxyx()[0] > VISUALIZER_HEIGHT + 3
        )

        if self.can_visualize:
            if self.visualizer_data.loaded_song != self.song_path:
                if self.visualizer_data.loaded_song is None:
                    self.can_visualize = False
                elif not self.visualizer_data.loading:
                    t = threading.Thread(
                        target=lambda: self.visualizer_data.__init__(
                            self.song_path
                        ),
                        daemon=True,
                    )
                    t.start()

        self.scroller.resize(
            self.stdscr.getmaxyx()[0]
            - 2  # -2 for status bar
            - 1  # -1 for header
            - (self.adding_song != None)  # -1 for add mode
            - (VISUALIZER_HEIGHT if self.can_visualize else 0)  # -visualizer
        )

        if self.clip_mode:
            pos -= self.clip[0]

        self.stdscr.clear()

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
            if self.can_visualize:
                if self.visualizer_data.loading:
                    visualize_message = "Loading visualization..."
            else:
                if self.stdscr.getmaxyx()[0] <= VISUALIZER_HEIGHT + 3:
                    visualize_message = "Window too small for visualization."
                else:
                    visualize_message = "Failed to load visualization."
                visualize_color = 14
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
        progress_bar_display_color = 17 if self.clip_mode else 15

        for j in range(
            self.scroller.top, self.scroller.top + self.scroller.win_size
        ):
            if j <= len(self.playlist) - 1:
                length_so_far = 0

                length_so_far = addstr_fit_to_width(
                    self.stdscr,
                    f"{j + 1} ",
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
                    length_so_far = addstr_fit_to_width(
                        self.stdscr,
                        f"({self.playlist[j][0]}) ",
                        screen_width,
                        length_so_far,
                        curses.color_pair(song_display_color) | curses.A_BOLD,
                    )
                else:
                    length_so_far = addstr_fit_to_width(
                        self.stdscr,
                        f"{self.playlist[j][1]} ({self.playlist[j][0]}) ",
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

        if self.adding_song is not None:
            # pylint: disable=unsubscriptable-object
            adding_song_length = addstr_fit_to_width(
                self.stdscr,
                "Add song (by ID): " + self.adding_song[0],
                screen_width,
                0,
                False,
                curses.color_pair(1),
            )
            self.stdscr.move(self.stdscr.getyx()[0] + 1, 0)

        length_so_far = 0

        length_so_far = addstr_fit_to_width(
            self.stdscr,
            ("| " if self.paused else "> ") + f"({self.playlist[self.i][0]}) ",
            screen_width,
            length_so_far,
            curses.color_pair(song_display_color + 10) | curses.A_BOLD,
        )
        length_so_far = addstr_fit_to_width(
            self.stdscr,
            f"{self.playlist[self.i][1]} ",
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
        length_so_far = addstr_fit_to_width(
            self.stdscr,
            f"{'l' if self.looping_current_song else ' '}",
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
            - 1
            - (VISUALIZER_HEIGHT if self.can_visualize else 0),
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
            if screen_width - length_so_far >= MIN_PROGRESS_BAR_WIDTH + 2:
                progress_bar_width = screen_width - length_so_far - 2
                bar = "|"
                progress_block_width = (
                    progress_bar_width * 8 * pos
                ) // self.duration
                for _ in range(progress_bar_width):
                    if progress_block_width > 8:
                        bar += HORIZONTAL_BLOCKS[8]
                        progress_block_width -= 8
                    elif progress_block_width > 0:
                        bar += HORIZONTAL_BLOCKS[progress_block_width]
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
                - 2
                - (VISUALIZER_HEIGHT if self.can_visualize else 0),
                volume_line_length_so_far,
            )
            if (
                screen_width - volume_line_length_so_far
                >= MIN_VOLUME_BAR_WIDTH + 10
            ):
                bar = f"{str(int(self.volume*100)).rjust(3)}/100 |"
                volume_bar_width = min(
                    screen_width - volume_line_length_so_far - (len(bar) + 1),
                    MAX_VOLUME_BAR_WIDTH,
                )
                block_width = int(volume_bar_width * 8 * self.volume)
                for _ in range(volume_bar_width):
                    if block_width > 8:
                        bar += HORIZONTAL_BLOCKS[8]
                        block_width -= 8
                    elif block_width > 0:
                        bar += HORIZONTAL_BLOCKS[block_width]
                        block_width = 0
                    else:
                        bar += " "
                bar += "|"
                bar = bar.rjust(screen_width - volume_line_length_so_far)

                self.stdscr.addstr(bar, curses.color_pair(16))
            elif screen_width - volume_line_length_so_far >= 7:
                self.stdscr.addstr(
                    f"{str(int(self.volume*100)).rjust(3)}/100".rjust(
                        screen_width - volume_line_length_so_far
                    ),
                    curses.color_pair(16),
                )

        if self.can_visualize:
            if self.clip_mode:
                pos += self.clip[0]

            self.stdscr.move(
                self.stdscr.getmaxyx()[0]
                - (VISUALIZER_HEIGHT if self.can_visualize else 0),
                0,
            )
            if self.visualizer_data.loading in (True, None):
                self.stdscr.addstr(
                    (
                        (" " * (self.stdscr.getmaxyx()[1] - 1) + "\n")
                        * VISUALIZER_HEIGHT
                    ).rstrip()
                )
            else:
                self.stdscr.addstr(
                    render(
                        self.stdscr.getmaxyx()[1] - 1,
                        self.visualizer_data.freqs,
                        min(
                            round(pos * FPS),
                            self.visualizer_data.freqs.shape[2] - 1,
                        ),
                    )
                )

        if self.adding_song is not None:
            # pylint: disable=unsubscriptable-object
            self.stdscr.move(
                self.stdscr.getmaxyx()[0]
                - (VISUALIZER_HEIGHT if self.can_visualize else 0)
                - 3,  # 3 lines for progress bar, status bar, and adding entry
                adding_song_length
                + (self.adding_song[1] - len(self.adding_song[0])),
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
    # curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_GREEN)
    # curses.init_pair(9, curses.COLOR_BLUE, curses.COLOR_GREEN)
    # curses.init_pair(10, curses.COLOR_YELLOW, curses.COLOR_GREEN)
    # curses.init_pair(11, curses.COLOR_GREEN, curses.COLOR_GREEN)
    curses.init_pair(12, curses.COLOR_BLACK + 8, curses.COLOR_BLACK)
    curses.init_pair(13, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(14, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(15, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(16, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(17, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
    # endregion

    curses.curs_set(False)
    stdscr.nodelay(True)
    curses.set_escdelay(25)  # 25 ms


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
    gen_vis_cache,
):
    song_name = os.path.split(path)[1]
    if "|" in song_name:
        click.secho(
            f"The song \"{song_name}\" contains one or more '|' character(s), which is not allowed—all ocurrences have been replaced with '-'.",
            fg="yellow",
        )
        song_name = song_name.replace("|", "-")

    for line in lines:
        details = line.split("|")
        if details[1] == song_name:
            click.secho(
                f"Song with name '{song_name}' already exists, 'copy' will be appended to the song name.",
                fg="yellow",
            )
            song_basename, song_ext = os.path.splitext(song_name)
            song_name = song_basename + " copy" + song_ext
            break
    dest_path = os.path.join(SONGS_DIR, song_name)

    if move_:
        move(path, dest_path)
    else:
        copy(path, dest_path)

    tags = list(set(tags))

    if prepend_newline:
        songs_file.write("\n")
    songs_file.write(f"{song_id}|{song_name}|{','.join(tags)}|")
    if clip_start is not None:
        songs_file.write(f"{clip_start} {clip_end}")
    songs_file.write("\n")

    for stats_file in os.listdir(STATS_DIR):
        if not stats_file.endswith(".txt"):
            continue

        with open(
            os.path.join(STATS_DIR, stats_file), "r+", encoding="utf-8"
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

    if gen_vis_cache:
        data = AudioData(os.path.join(SONGS_DIR, song_name), data=False)
        if data.loaded_song is None:
            data = None
    else:
        data = None

    click.secho(
        f"Added{' and cached visualization frequencies for' if data is not None else ''} song '{song_name}' with ID {song_id}"
        + tags_string
        + clip_string
        + ".",
        fg="green",
    )


def format_seconds(secs, show_decimal=False):
    """Format seconds into a string."""
    return f"{int(secs//60):02}:{int(secs%60):02}" + (
        f".{secs%1:0.2f}"[2:] if show_decimal else ""
    )


def print_entry(entry_list):
    """
    tuple or iterable of strings

    0: song ID
    1: song name
    2: tags
    3: clip

    optional:
    4: seconds listened
    5: total duration (must be passed if 3 is passed)

    Pretty prints '<song ID> <song name> [<total duration> <seconds
    listened> <times listened>] <clip> <tags>'"""
    click.secho(entry_list[0] + " ", fg="bright_black", nl=False)
    click.secho(entry_list[1] + " ", fg="blue", nl=False)

    if len(entry_list) > 4:  # len should == 6
        secs_listened = float(entry_list[4])
        total_duration = float(entry_list[5])
        click.secho(
            format_seconds(total_duration, show_decimal=True) + " ",
            nl=False,
        )
        click.secho(
            format_seconds(secs_listened, show_decimal=True) + " ",
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
