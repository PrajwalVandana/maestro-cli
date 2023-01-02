import curses
import os

from shutil import copy, move
from datetime import date

import click


# region constants

CUR_YEAR = date.today().year

MAESTRO_DIR = os.path.join(os.path.expanduser("~"), ".maestro-files/")
SONGS_DIR = os.path.join(MAESTRO_DIR, "songs/")
SONGS_INFO_PATH = os.path.join(MAESTRO_DIR, "songs.txt")
STATS_DIR = os.path.join(MAESTRO_DIR, "stats/")
CUR_YEAR_STATS_PATH = os.path.join(STATS_DIR, f"{CUR_YEAR}.txt")
TOTAL_STATS_PATH = os.path.join(STATS_DIR, "total.txt")

EXTS = (".mp3", ".wav", ".flac", ".ogg")

SCRUB_TIME = 5  # in seconds
VOLUME_STEP = 0.01  # self.volume is 0-1
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
MIN_PROGRESS_BAR_WIDTH = 20
MIN_VOLUME_BAR_WIDTH, MAX_VOLUME_BAR_WIDTH = 10, 40

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
    line_over = False
    if length_so_far + len(string) > width:
        line_over = True
        remaining_width = width - length_so_far
        if remaining_width >= 3:
            string = string[: (remaining_width - 3)].rstrip() + "...\n"
        else:
            string = "..."[:remaining_width] + "\n"
    length_so_far += len(string)
    return string, length_so_far, line_over


def addstr_fit_to_width(
    stdscr, string, width, length_so_far, line_over, *args, **kwargs
):
    if not line_over:
        string, length_so_far, line_over = fit_string_to_width(
            string, width, length_so_far
        )
        if string:
            stdscr.addstr(string, *args, **kwargs)
    return length_so_far, line_over


class PlayerOutput:
    def __init__(self, stdscr, playlist, volume, clip_mode):
        self.stdscr = stdscr
        self.scroller = Scroller(
            len(playlist), stdscr.getmaxyx()[0] - 2  # -2 for status bar
        )
        self.playlist = playlist
        self.volume = volume

        self.i = 0
        self.looping_current_song = False
        self.duration = 0
        self.paused = False
        self.ending = False
        self.adding_song: None | tuple = None
        self.clip_mode = clip_mode
        self.clip = (0, 0)

    def output(self, pos):
        if self.clip_mode:
            pos -= self.clip[0]

        self.stdscr.clear()
        # NOTE: terminal prints newline for some reason if len(string) == width, so
        # NOTE:   we subtract 1
        screen_width = self.stdscr.getmaxyx()[1] - 1

        song_display_color = 5 if self.looping_current_song else 3
        progress_bar_display_color = 17 if self.clip_mode else 15

        for j in range(
            self.scroller.top, self.scroller.top + self.scroller.win_size
        ):
            if j > len(self.playlist) - 1:
                self.stdscr.addstr("\n")
            else:
                length_so_far, line_over = 0, False

                length_so_far, line_over = addstr_fit_to_width(
                    self.stdscr,
                    f"{j + 1} ",
                    screen_width,
                    length_so_far,
                    line_over,
                    curses.color_pair(2),
                )
                if j == self.i:
                    length_so_far, line_over = addstr_fit_to_width(
                        self.stdscr,
                        f"{self.playlist[j][1]} ",
                        screen_width,
                        length_so_far,
                        line_over,
                        curses.color_pair(song_display_color) | curses.A_BOLD,
                    )
                    length_so_far, line_over = addstr_fit_to_width(
                        self.stdscr,
                        f"({self.playlist[j][0]}) ",
                        screen_width,
                        length_so_far,
                        line_over,
                        curses.color_pair(song_display_color) | curses.A_BOLD,
                    )
                else:
                    length_so_far, line_over = addstr_fit_to_width(
                        self.stdscr,
                        f"{self.playlist[j][1]} ({self.playlist[j][0]}) ",
                        screen_width,
                        length_so_far,
                        line_over,
                        (
                            curses.color_pair(4)
                            if (j == self.scroller.pos)
                            else curses.color_pair(1)
                        ),
                    )
                length_so_far, line_over = addstr_fit_to_width(
                    self.stdscr,
                    f"{', '.join(self.playlist[j][2].split(','))}\n",
                    screen_width,
                    length_so_far,
                    line_over,
                    curses.color_pair(2),
                )

        if self.adding_song is not None:
            # pylint: disable=unsubscriptable-object
            adding_song_length, line_over = addstr_fit_to_width(
                self.stdscr,
                "Add song (by ID): " + self.adding_song[0] + "\n",
                screen_width,
                0,
                False,
                curses.color_pair(1),
            )
            if line_over:
                adding_song_length -= 1  # newline doesn't count

        length_so_far, line_over = 0, False

        length_so_far, line_over = addstr_fit_to_width(
            self.stdscr,
            ("| " if self.paused else "> ") + f"({self.playlist[self.i][0]}) ",
            screen_width,
            length_so_far,
            line_over,
            curses.color_pair(song_display_color + 10) | curses.A_BOLD,
        )
        length_so_far, line_over = addstr_fit_to_width(
            self.stdscr,
            f"{self.playlist[self.i][1]} ",
            screen_width,
            length_so_far,
            line_over,
            curses.color_pair(song_display_color + 10) | curses.A_BOLD,
        )
        length_so_far, line_over = addstr_fit_to_width(
            self.stdscr,
            "%d/%d " % (self.i + 1, len(self.playlist)),
            screen_width,
            length_so_far,
            line_over,
            curses.color_pair(12),
        )
        length_so_far, line_over = addstr_fit_to_width(
            self.stdscr,
            f"{'c' if self.clip_mode else ' '}",
            screen_width,
            length_so_far,
            line_over,
            curses.color_pair(17),
        )
        volume_line_length_so_far, line_over = addstr_fit_to_width(
            self.stdscr,
            f"{'l' if self.looping_current_song else ' '}",
            screen_width,
            length_so_far,
            line_over,
            curses.color_pair(15),
        )
        volume_line_length_so_far, line_over = addstr_fit_to_width(
            self.stdscr,
            f"{'e' if self.ending else ' '}  ",
            screen_width,
            length_so_far,
            line_over,
            curses.color_pair(14),
        )
        if not line_over:
            addstr_fit_to_width(
                self.stdscr,
                " " * (screen_width - length_so_far),
                screen_width,
                volume_line_length_so_far,
                line_over,
                curses.color_pair(13),
            )

        length_so_far, line_over = 0, False
        secs = int(pos)
        length_so_far, line_over = addstr_fit_to_width(
            self.stdscr,
            f"{format_seconds(secs)} / {format_seconds(self.duration)}  ",
            screen_width,
            length_so_far,
            line_over,
            curses.color_pair(progress_bar_display_color),
        )
        if not line_over:
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
                bar += "|"

                length_so_far, line_over = addstr_fit_to_width(
                    self.stdscr,
                    bar,
                    screen_width,
                    length_so_far,
                    line_over,
                    curses.color_pair(progress_bar_display_color),
                )
            else:
                length_so_far, line_over = addstr_fit_to_width(
                    self.stdscr,
                    " " * (screen_width - length_so_far),
                    screen_width,
                    length_so_far,
                    line_over,
                    curses.color_pair(13),
                )

        try:
            # right align volume bar to (progress bar) length_so_far
            self.stdscr.move(
                self.stdscr.getmaxyx()[0] - 2, volume_line_length_so_far
            )
            if (
                length_so_far - volume_line_length_so_far
                >= MIN_VOLUME_BAR_WIDTH + 10
            ):
                volume_bar_width = min(
                    length_so_far - volume_line_length_so_far - 10,
                    MAX_VOLUME_BAR_WIDTH,
                )
                bar = f"{str(int(self.volume*100)).rjust(3)}/100 |"
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
                bar = bar.rjust(length_so_far - volume_line_length_so_far)

                length_so_far, line_over = addstr_fit_to_width(
                    self.stdscr,
                    bar,
                    length_so_far,
                    volume_line_length_so_far,
                    line_over,
                    curses.color_pair(16),
                )
            elif length_so_far - volume_line_length_so_far >= 7:
                length_so_far, line_over = addstr_fit_to_width(
                    self.stdscr,
                    f"{str(int(self.volume*100)).rjust(3)}/100".rjust(
                        length_so_far - volume_line_length_so_far
                    ),
                    length_so_far,
                    volume_line_length_so_far,
                    line_over,
                    curses.color_pair(16),
                )
                addstr_fit_to_width(
                    self.stdscr,
                    " " * (screen_width - length_so_far),
                    screen_width,
                    length_so_far,
                    line_over,
                    curses.color_pair(13),
                )
        except curses.error:
            pass

        if self.adding_song is not None:
            # adding_song_length-1 b/c 0-indexed
            # pylint: disable=unsubscriptable-object
            self.stdscr.move(
                self.stdscr.getmaxyx()[0] - 3,
                adding_song_length
                - 1
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
):
    song_name = os.path.split(path)[1]
    dest_path = os.path.join(SONGS_DIR, song_name)

    for line in lines:
        details = line.split("|")
        if details[1] == song_name:
            click.secho(
                f"Song with name '{song_name}' already exists, 'copy' will be appended to the song name",
                fg="yellow",
            )
            song_name += " copy"
            return

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

    with (
        open(TOTAL_STATS_PATH, "r+", encoding="utf-8") as total_stats_file,
        open(
            CUR_YEAR_STATS_PATH, "r+", encoding="utf-8"
        ) as cur_year_stats_file,
    ):
        total_stats_file_contents = total_stats_file.read()
        if (
            total_stats_file_contents
            and not total_stats_file_contents.endswith("\n")
        ):
            total_stats_file.write("\n")
        total_stats_file.write(f"{song_id}|0\n")

        cur_year_stats_file_contents = cur_year_stats_file.read()
        if (
            cur_year_stats_file_contents
            and not cur_year_stats_file_contents.endswith("\n")
        ):
            cur_year_stats_file.write("\n")
        cur_year_stats_file.write(f"{song_id}|0\n")

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

    click.secho(
        f"Added song '{song_name}' with ID {song_id}"
        + tags_string
        + clip_string,
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
