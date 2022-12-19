# region imports
import curses
import multiprocessing
import os
import sys

import click

from random import shuffle, randint
from shutil import copy, move
from time import sleep

from just_playback import Playback
from tinytag import TinyTag

try:
    import pypresence

    can_update_discord = True
    discord_rpc = pypresence.Presence(client_id=1039038199881810040)
except ImportError:
    can_update_discord = False

# endregion


MAESTRO_DIR = os.path.join(os.path.expanduser("~"), ".maestro-files/")
SONGS_DIR = os.path.join(MAESTRO_DIR, "songs/")
SONGS_INFO_PATH = os.path.join(MAESTRO_DIR, "songs.txt")

if sys.platform == "darwin":
    try:
        # pylint: disable=no-name-in-module,import-error
        from AppKit import NSRunLoop, NSDate, NSApplication, NSImage
        from MediaPlayer import MPNowPlayingInfoPropertyElapsedPlaybackTime

        # import UIImage


        from mac_presence import MacNowPlaying

        # globals
        mac_now_playing = MacNowPlaying()

        # get image from file for Now Playing thumbnail
        # with open("./maestro_icon.png", "rb") as f:
        #     cover_img = f.read()
        # print(cover_img)

        can_mac_now_playing = True
    except:
        can_mac_now_playing = False

EXTS = (".mp3", ".wav", ".flac", ".ogg")

SCRUB_TIME = 5  # in seconds
VOLUME_STEP = 0.01  # volume is 0-1
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

# region utility functions/classes


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


def clear_screen():
    if os.name == "posix":
        os.system("clear")
    else:
        click.clear()


def mac_now_playing_loop(q, song_name_queue, duration, paused, pos):
    global can_mac_now_playing

    try:
        mac_now_playing.q = q
        mac_now_playing.pos = pos

        song_name = ""
        while not song_name_queue.empty():
            song_name += song_name_queue.get()
        mac_now_playing.play(
            "maestro-cli",
            song_name,
            paused.value,
            duration.value,
            pos.value,
            None,
        )
        # ns_application = NSApplication.sharedApplication()
        # logo_ns_image = NSImage.alloc().initByReferencingFile_('./maestro_icon.png')
        # ns_application.setApplicationIconImage_(logo_ns_image)
        # print(dir(mac_now_playing.info_center), file=open("log.txt", "w"))
        # print(cover_img)

        while True:
            if not song_name_queue.empty():
                while not song_name_queue.empty():
                    song_name = ""
                    c = song_name_queue.get()
                    while c != "\n":
                        song_name += c
                        c = song_name_queue.get()
            mac_now_playing.play(
                "maestro-cli",
                song_name,
                paused.value,
                duration.value,
                pos.value,
                None,
            )
            # elif (
            #     abs(
            #         pos.value
            #         - mac_now_playing.info_center.nowPlayingInfo()[
            #             MPNowPlayingInfoPropertyElapsedPlaybackTime
            #         ]
            #     )
            #     > 2
            # ):
            #     mac_now_playing.play(
            #         "maestro-cli",
            #         song_name,
            #         paused.value,
            #         duration.value,
            #         pos.value,
            #         None,
            #     )

            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )
            # sleep(0.1)
    except:
        can_mac_now_playing = False


def discord_presence_loop(song_name_queue):
    try:
        discord_rpc.connect()
        discord_connected = True
    except ConnectionRefusedError:
        discord_connected = False
    while True:
        if not song_name_queue.empty():
            while not song_name_queue.empty():
                song_name = ""
                c = song_name_queue.get()
                while c != "\n":
                    song_name += c
                    c = song_name_queue.get()
            if discord_connected:
                try:
                    discord_rpc.update(
                        details="Listening to",
                        state=song_name,
                        large_image="maestro-icon",
                    )
                    song_name = ""
                    sleep(15)
                except pypresence.exceptions.InvalidID:
                    discord_connected = False
            else:
                try:
                    discord_rpc.connect()
                    discord_connected = True
                except ConnectionRefusedError:
                    pass
                if discord_connected:
                    try:
                        discord_rpc.update(
                            details="Listening to",
                            state=song_name,
                            large_image="maestro-icon",
                        )
                        song_name = ""
                        sleep(15)
                    except pypresence.exceptions.InvalidID:
                        discord_connected = False


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


def output(
    stdscr,
    scroller,
    i,
    playlist,
    looping,
    volume,
    duration,
    pos,
    paused,
    adding_song,
):
    # NOTE: terminal prints newline for some reason if len(string) == width, so
    # NOTE:   we subtract 1
    screen_width = stdscr.getmaxyx()[1] - 1

    for j in range(scroller.top, scroller.top + scroller.win_size):
        if j > len(playlist) - 1:
            stdscr.addstr("\n")
        else:
            length_so_far, line_over = 0, False

            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                f"{j + 1} ",
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(2),
            )
            if j == i:
                length_so_far, line_over = addstr_fit_to_width(
                    stdscr,
                    f"{playlist[j][1]} ",
                    screen_width,
                    length_so_far,
                    line_over,
                    curses.color_pair(3) | curses.A_BOLD,
                )
                length_so_far, line_over = addstr_fit_to_width(
                    stdscr,
                    f"({playlist[j][0]}) ",
                    screen_width,
                    length_so_far,
                    line_over,
                    curses.color_pair(3),
                )
            else:
                length_so_far, line_over = addstr_fit_to_width(
                    stdscr,
                    f"{playlist[j][1]} ({playlist[j][0]}) ",
                    screen_width,
                    length_so_far,
                    line_over,
                    (
                        curses.color_pair(4)
                        if (j == scroller.pos)
                        else curses.color_pair(1)
                    ),
                )
            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                f"{', '.join(playlist[j][2].split(','))}\n",
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(2),
            )

    if adding_song is not None:
        adding_song_length, line_over = addstr_fit_to_width(
            stdscr,
            "Add song (by ID): " + adding_song[0] + "\n",
            screen_width,
            0,
            False,
            curses.color_pair(1),
        )
        if line_over:
            adding_song_length -= 1  # newline doesn't count

    length_so_far, line_over = 0, False

    length_so_far, line_over = addstr_fit_to_width(
        stdscr,
        ("| " if paused else "> ") + f"({playlist[i][0]}) ",
        screen_width,
        length_so_far,
        line_over,
        curses.color_pair(13),
    )
    length_so_far, line_over = addstr_fit_to_width(
        stdscr,
        f"{playlist[i][1]} ",
        screen_width,
        length_so_far,
        line_over,
        curses.color_pair(13) | curses.A_BOLD,
    )
    volume_line_length_so_far, line_over = addstr_fit_to_width(
        stdscr,
        "%d/%d  " % (i + 1, len(playlist)),
        screen_width,
        length_so_far,
        line_over,
        curses.color_pair(12),
    )
    if not line_over:
        addstr_fit_to_width(
            stdscr,
            " " * (screen_width - length_so_far),
            screen_width,
            volume_line_length_so_far,
            line_over,
            curses.color_pair(13),
        )
        # stdscr.addstr("\n")

    length_so_far, line_over = 0, False
    secs = int(pos)
    length_so_far, line_over = addstr_fit_to_width(
        stdscr,
        f"{secs//60:02}:{secs%60:02} / {duration//60:02}:{duration%60:02}  ",
        screen_width,
        length_so_far,
        line_over,
        curses.color_pair(15),
    )
    if not line_over:
        if screen_width - length_so_far >= MIN_PROGRESS_BAR_WIDTH + 2:
            progress_bar_width = screen_width - length_so_far - 2
            bar = "|"
            progress_block_width = (progress_bar_width * 8 * pos) // duration
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
                stdscr,
                bar,
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(15),
            )
        else:
            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                " " * (screen_width - length_so_far),
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(13),
            )
    # if not line_over:
    #     addstr_fit_to_width(
    #         stdscr,
    #         " " * (screen_width - length_so_far),
    #         screen_width,
    #         length_so_far,
    #         line_over,
    #         curses.color_pair(13),
    #     )

    try:
        # right align volume bar to (progress bar) length_so_far
        stdscr.move(stdscr.getmaxyx()[0] - 2, volume_line_length_so_far)
        # volume_line_length_so_far, line_over = addstr_fit_to_width(
        #     stdscr,
        #     f"vol: {str(int(volume*100)).rjust(3)}/100 ",
        #     screen_width,
        #     volume_line_length_so_far,
        #     line_over,
        #     curses.color_pair(16),
        # )
        if (
            length_so_far - volume_line_length_so_far
            >= MIN_VOLUME_BAR_WIDTH + 10
        ):
            volume_bar_width = min(
                length_so_far - volume_line_length_so_far - 10,
                MAX_VOLUME_BAR_WIDTH,
            )
            bar = f"{str(int(volume*100)).rjust(3)}/100 |"
            block_width = int(volume_bar_width * 8 * volume)
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
                stdscr,
                bar,
                length_so_far,
                volume_line_length_so_far,
                line_over,
                curses.color_pair(16),
            )
            # addstr_fit_to_width(
            #     stdscr,
            #     " " * (screen_width - length_so_far),
            #     screen_width,
            #     length_so_far,
            #     line_over,
            #     curses.color_pair(13),
            # )
        elif length_so_far - volume_line_length_so_far >= 7:
            length_so_far, line_over = addstr_fit_to_width(
                stdscr,
                f"{str(int(volume*100)).rjust(3)}/100".rjust(
                    length_so_far - volume_line_length_so_far
                ),
                length_so_far,
                volume_line_length_so_far,
                line_over,
                curses.color_pair(16),
            )
            addstr_fit_to_width(
                stdscr,
                " " * (screen_width - length_so_far),
                screen_width,
                length_so_far,
                line_over,
                curses.color_pair(13),
            )
    except curses.error:
        pass
    if adding_song is not None:
        # adding_song_length-1 b/c 0-indexed
        stdscr.move(
            stdscr.getmaxyx()[0] - 3,
            adding_song_length - 1 + (adding_song[1] - len(adding_song[0])),
        )


def _add(path, tags, move_, songs_file, lines, song_id, prepend_newline):
    song_name = os.path.split(path)[1]
    dest_path = os.path.join(SONGS_DIR, song_name)

    for line in lines:
        details = line.split("|")
        if details[1] == song_name:
            click.secho(
                f"Song with name '{song_name}' already exists", fg="red"
            )
            return

    if move_:
        move(path, dest_path)
    else:
        copy(path, dest_path)

    tags = list(set(tags))

    if prepend_newline:
        songs_file.write("\n")
    songs_file.write(f"{song_id}|{song_name}|{','.join(tags)}\n")

    if not tags:
        tags_string = ""
    elif len(tags) == 1:
        tags_string = f' and tag "{tags[0]}"'
    else:
        tags_string = f" and tags {', '.join([repr(tag) for tag in tags])}"
    click.secho(
        f"Added song '{song_name}' with id {song_id}" + tags_string, fg="green"
    )


def _play(stdscr, playlist, volume, loop, reshuffle, update_discord):
    # region curses setup
    curses.start_color()
    curses.curs_set(False)
    curses.use_default_colors()
    stdscr.nodelay(True)
    curses.set_escdelay(25)  # 25 ms

    curses.init_pair(1, curses.COLOR_WHITE, -1)
    if curses.can_change_color():
        curses.init_pair(2, curses.COLOR_BLACK + 8, -1)
    else:
        curses.init_pair(2, curses.COLOR_BLACK, -1)
    curses.init_pair(3, curses.COLOR_BLUE, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_YELLOW, -1)
    curses.init_pair(6, curses.COLOR_GREEN, -1)
    # curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_GREEN)
    # curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_GREEN)
    # curses.init_pair(9, curses.COLOR_BLUE, curses.COLOR_GREEN)
    # curses.init_pair(10, curses.COLOR_YELLOW, curses.COLOR_GREEN)
    # curses.init_pair(11, curses.COLOR_GREEN, curses.COLOR_GREEN)
    if curses.can_change_color():
        curses.init_pair(12, curses.COLOR_BLACK + 8, curses.COLOR_BLACK)
    else:
        curses.init_pair(12, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(13, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(14, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(15, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(16, curses.COLOR_GREEN, curses.COLOR_BLACK)
    # endregion

    scroller = Scroller(
        len(playlist), stdscr.getmaxyx()[0] - 2  # -2 for status bar
    )

    if loop:
        next_playlist = playlist[:]
        if reshuffle:
            shuffle(next_playlist)
    else:
        next_playlist = None

    if update_discord:
        discord_song_name_queue = multiprocessing.SimpleQueue()
        discord_presence_process = multiprocessing.Process(
            daemon=True,
            target=discord_presence_loop,
            args=(discord_song_name_queue,),
        )
        discord_presence_process.start()

    if sys.platform == "darwin" and can_mac_now_playing:
        is_paused = multiprocessing.Value("i", 0)  # bool (0 or 1)
        # similar to discord_song_name_queue
        now_playing_song_name_queue = multiprocessing.SimpleQueue()
        now_playing_duration = multiprocessing.Value(
            "l", 0
        )  # long (in seconds)
        now_playing_pos = multiprocessing.Value("l", 0)  # long (in seconds)
        now_playing_actions_queue = multiprocessing.SimpleQueue()
        mac_now_playing_process = multiprocessing.Process(
            daemon=True,
            target=mac_now_playing_loop,
            args=(
                now_playing_actions_queue,
                now_playing_song_name_queue,
                now_playing_duration,
                is_paused,
                now_playing_pos,
            ),
        )
        mac_now_playing_process.start()
        # return

    i = 0
    adding_song: None | tuple = None
    prev_volume = volume
    while i in range(len(playlist)):
        paused = False

        song_path = os.path.join(SONGS_DIR, playlist[i][1])
        duration = int(TinyTag.get(song_path).duration)

        if sys.platform == "darwin" and can_mac_now_playing:
            is_paused.value = int(paused)
            now_playing_duration.value = duration
            now_playing_pos.value = 0

            for c in playlist[i][1]:
                now_playing_song_name_queue.put(c)
            now_playing_song_name_queue.put("\n")

        if update_discord:
            for c in playlist[i][1]:
                discord_song_name_queue.put(c)
            discord_song_name_queue.put("\n")

        playback = Playback()
        playback.load_file(song_path)
        playback.play()
        playback.set_volume(volume)

        stdscr.clear()
        output(
            stdscr,
            scroller,
            i,
            playlist,
            loop,
            volume,
            duration,
            playback.curr_pos,
            paused,
            adding_song,
        )
        stdscr.refresh()

        frame_duration = 1

        last_timestamp = playback.curr_pos
        next_song = 1  # -1 if going back, 0 if restarting, +1 if next song
        while True:
            if not playback.active:
                next_song = 1
                break

            if sys.platform == "darwin" and can_mac_now_playing:
                if abs(playback.curr_pos - now_playing_pos.value) > 2:
                    playback.seek(now_playing_pos.value)
                else:
                    now_playing_pos.value = int(playback.curr_pos)

            if (
                sys.platform == "darwin"
                and can_mac_now_playing
                and not now_playing_actions_queue.empty()
            ):
                c = now_playing_actions_queue.get()
                if c in "nNsS":
                    if i == len(playlist) - 1 and not loop:
                        pass
                    else:
                        next_song = 1
                        playback.stop()
                        break
                elif c in "bBpP":
                    if i == 0:
                        pass
                    else:
                        next_song = -1
                        playback.stop()
                        break
                elif c in "rR":
                    playback.stop()
                    next_song = 0
                    break
                elif c in "eEqQ":
                    playback.stop()
                    return
                elif c == " ":
                    if paused:
                        paused = False
                        playback.resume()
                    else:
                        paused = True
                        playback.pause()
                    if sys.platform == "darwin" and can_mac_now_playing:
                        is_paused.value = int(paused)

                    stdscr.clear()
                    output(
                        stdscr,
                        scroller,
                        i,
                        playlist,
                        loop,
                        volume,
                        duration,
                        playback.curr_pos,
                        paused,
                        adding_song,
                    )
                    stdscr.refresh()
                elif c == "LEFT" * 2:
                    playback.seek(playback.curr_pos - SCRUB_TIME * 2)
                    now_playing_pos.value = int(playback.curr_pos)

                    last_timestamp = playback.curr_pos
                    stdscr.clear()
                    output(
                        stdscr,
                        scroller,
                        i,
                        playlist,
                        loop,
                        volume,
                        duration,
                        playback.curr_pos,
                        paused,
                        adding_song,
                    )
                    stdscr.refresh()
                elif c == "RIGHT" * 2:
                    playback.seek(playback.curr_pos + SCRUB_TIME * 2)
                    now_playing_pos.value = int(playback.curr_pos)

                    last_timestamp = playback.curr_pos
                    stdscr.clear()
                    output(
                        stdscr,
                        scroller,
                        i,
                        playlist,
                        loop,
                        volume,
                        duration,
                        playback.curr_pos,
                        paused,
                        adding_song,
                    )
                    stdscr.refresh()
            else:
                c = stdscr.getch()
                if c != -1:
                    if adding_song is None:
                        if c == curses.KEY_LEFT:
                            playback.seek(playback.curr_pos - SCRUB_TIME)
                            if sys.platform == "darwin" and can_mac_now_playing:
                                now_playing_pos.value = int(playback.curr_pos)

                            last_timestamp = playback.curr_pos
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_RIGHT:
                            playback.seek(playback.curr_pos + SCRUB_TIME)
                            if sys.platform == "darwin" and can_mac_now_playing:
                                now_playing_pos.value = int(playback.curr_pos)

                            last_timestamp = playback.curr_pos
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_UP:
                            if scroller.pos != 0:
                                scroller.scroll_backward()
                                stdscr.clear()
                                output(
                                    stdscr,
                                    scroller,
                                    i,
                                    playlist,
                                    loop,
                                    volume,
                                    duration,
                                    playback.curr_pos,
                                    paused,
                                    adding_song,
                                )
                                stdscr.refresh()
                        elif c == curses.KEY_DOWN:
                            if scroller.pos != scroller.num_lines - 1:
                                scroller.scroll_forward()
                                stdscr.clear()
                                output(
                                    stdscr,
                                    scroller,
                                    i,
                                    playlist,
                                    loop,
                                    volume,
                                    duration,
                                    playback.curr_pos,
                                    paused,
                                    adding_song,
                                )
                                stdscr.refresh()
                        elif c == curses.KEY_ENTER:
                            i = scroller.pos - 1
                            next_song = 1
                            playback.stop()
                            break
                        elif c == curses.KEY_RESIZE:
                            screen_size = stdscr.getmaxyx()
                            scroller.resize(screen_size[0] - 2)
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        else:
                            try:
                                c = chr(c)
                                if c in "nNsS":
                                    if i == len(playlist) - 1 and not loop:
                                        pass
                                    else:
                                        next_song = 1
                                        playback.stop()
                                        break
                                elif c in "bBpP":
                                    if i == 0:
                                        pass
                                    else:
                                        next_song = -1
                                        playback.stop()
                                        break
                                elif c in "rR":
                                    playback.stop()
                                    next_song = 0
                                    break
                                elif c in "eEqQ":
                                    playback.stop()
                                    return
                                elif c in "dD":
                                    selected_song = scroller.pos
                                    del playlist[selected_song]
                                    scroller.num_lines -= 1
                                    if selected_song == i:  # deleted current song
                                        next_song = 1
                                        # will be incremented to i
                                        scroller.pos = i - 1
                                        i -= 1
                                        playback.stop()
                                        break
                                    # deleted song before current
                                    if selected_song < i:
                                        i -= 1
                                elif c in "aA":
                                    adding_song = "", 0
                                    curses.curs_set(True)
                                    screen_size = stdscr.getmaxyx()
                                    scroller.resize(screen_size[0] - 3)
                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                                elif c in "mM":
                                    if volume == 0:
                                        volume = prev_volume
                                    else:
                                        volume = 0
                                    playback.set_volume(volume)

                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                                elif c == " ":
                                    if paused:
                                        paused = False
                                        playback.resume()
                                    else:
                                        paused = True
                                        playback.pause()
                                    if (
                                        sys.platform == "darwin"
                                        and can_mac_now_playing
                                    ):
                                        is_paused.value = int(paused)

                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                                elif c == "[":
                                    volume = max(0, volume - VOLUME_STEP)
                                    playback.set_volume(volume)

                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()

                                    prev_volume = volume
                                elif c == "]":
                                    volume = min(1, volume + VOLUME_STEP)
                                    playback.set_volume(volume)

                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()

                                    prev_volume = volume
                                elif c in "\r\n":
                                    i = scroller.pos - 1
                                    next_song = 1
                                    playback.stop()
                                    break
                            except (ValueError, OverflowError):
                                pass
                    else:
                        if c == curses.KEY_RESIZE:
                            screen_size = stdscr.getmaxyx()
                            scroller.resize(screen_size[0] - 3)
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_LEFT:
                            # pylint: disable=unsubscriptable-object
                            adding_song = adding_song[0], max(adding_song[1] - 1, 0)
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_RIGHT:
                            # pylint: disable=unsubscriptable-object
                            adding_song = adding_song[0], min(
                                adding_song[1] + 1, len(adding_song[0])
                            )
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_UP:
                            if scroller.pos != 0:
                                scroller.scroll_backward()
                                stdscr.clear()
                                output(
                                    stdscr,
                                    scroller,
                                    i,
                                    playlist,
                                    loop,
                                    volume,
                                    duration,
                                    playback.curr_pos,
                                    paused,
                                    adding_song,
                                )
                                stdscr.refresh()
                        elif c == curses.KEY_DOWN:
                            if scroller.pos != scroller.num_lines - 1:
                                scroller.scroll_forward()
                                stdscr.clear()
                                output(
                                    stdscr,
                                    scroller,
                                    i,
                                    playlist,
                                    loop,
                                    volume,
                                    duration,
                                    playback.curr_pos,
                                    paused,
                                    adding_song,
                                )
                                stdscr.refresh()
                        elif c == curses.KEY_DC:
                            # pylint: disable=unsubscriptable-object
                            if adding_song[1] > 0:
                                adding_song = (
                                    adding_song[0][: adding_song[1] - 1]
                                    + adding_song[0][adding_song[1] :],
                                    adding_song[1] - 1,
                                )
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        elif c == curses.KEY_ENTER:
                            # pylint: disable=unsubscriptable-object
                            if adding_song[0].isnumeric():
                                for details in playlist:
                                    if int(details[0]) == int(adding_song[0]):
                                        break
                                else:
                                    with open(
                                        SONGS_INFO_PATH,
                                        "r",
                                        encoding="utf-8",
                                    ) as songs_file:
                                        for line in songs_file:
                                            details = line.strip().split("|")
                                            song_id = int(details[0])
                                            if song_id == int(adding_song[0]):
                                                playlist.append(details)
                                                if loop:
                                                    if reshuffle:
                                                        next_playlist.insert(
                                                            randint(
                                                                0,
                                                                len(next_playlist)
                                                                - 1,
                                                            ),
                                                            details,
                                                        )
                                                    else:
                                                        next_playlist.append(
                                                            details
                                                        )
                                                scroller.num_lines += 1
                                                adding_song = None
                                                curses.curs_set(False)
                                                scroller.resize(screen_size[0] - 2)
                                                stdscr.clear()
                                                output(
                                                    stdscr,
                                                    scroller,
                                                    i,
                                                    playlist,
                                                    loop,
                                                    volume,
                                                    duration,
                                                    playback.curr_pos,
                                                    paused,
                                                    adding_song,
                                                )
                                                stdscr.refresh()
                                                break
                        elif c == 27:  # ESC key
                            adding_song = None
                            curses.curs_set(False)
                            scroller.resize(screen_size[0] - 2)
                            stdscr.clear()
                            output(
                                stdscr,
                                scroller,
                                i,
                                playlist,
                                loop,
                                volume,
                                duration,
                                playback.curr_pos,
                                paused,
                                adding_song,
                            )
                            stdscr.refresh()
                        else:
                            try:
                                c = chr(c)
                                if c in "\r\n":
                                    # pylint: disable=unsubscriptable-object
                                    if adding_song[0].isnumeric():
                                        for details in playlist:
                                            if int(details[0]) == int(
                                                adding_song[0]
                                            ):
                                                break
                                        else:
                                            with open(
                                                SONGS_INFO_PATH,
                                                "r",
                                                encoding="utf-8",
                                            ) as songs_file:
                                                for line in songs_file:
                                                    details = line.strip().split(
                                                        "|"
                                                    )
                                                    song_id = int(details[0])
                                                    if song_id == int(
                                                        adding_song[0]
                                                    ):
                                                        playlist.append(details)
                                                        if loop:
                                                            if reshuffle:
                                                                next_playlist.insert(
                                                                    randint(
                                                                        0,
                                                                        len(
                                                                            next_playlist
                                                                        )
                                                                        - 1,
                                                                    ),
                                                                    details,
                                                                )
                                                            else:
                                                                next_playlist.append(
                                                                    details
                                                                )
                                                        scroller.num_lines += 1
                                                        adding_song = None
                                                        curses.curs_set(False)
                                                        scroller.resize(
                                                            screen_size[0] - 2
                                                        )
                                                        stdscr.clear()
                                                        output(
                                                            stdscr,
                                                            scroller,
                                                            i,
                                                            playlist,
                                                            loop,
                                                            volume,
                                                            duration,
                                                            playback.curr_pos,
                                                            paused,
                                                            adding_song,
                                                        )
                                                        stdscr.refresh()
                                                        break
                                elif c in "\b\x7f":
                                    # pylint: disable=unsubscriptable-object
                                    if adding_song[1] > 0:
                                        adding_song = (
                                            adding_song[0][: adding_song[1] - 1]
                                            + adding_song[0][adding_song[1] :],
                                            adding_song[1] - 1,
                                        )
                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                                else:
                                    adding_song = (
                                        # pylint: disable=unsubscriptable-object
                                        adding_song[0][: adding_song[1]]
                                        + c
                                        + adding_song[0][adding_song[1] :],
                                        adding_song[1] + 1,
                                    )
                                    stdscr.clear()
                                    output(
                                        stdscr,
                                        scroller,
                                        i,
                                        playlist,
                                        loop,
                                        volume,
                                        duration,
                                        playback.curr_pos,
                                        paused,
                                        adding_song,
                                    )
                                    stdscr.refresh()
                            except (ValueError, OverflowError):
                                pass

            if (playback.curr_pos - last_timestamp) > frame_duration:
                stdscr.clear()
                last_timestamp = playback.curr_pos
                output(
                    stdscr,
                    scroller,
                    i,
                    playlist,
                    loop,
                    volume,
                    duration,
                    playback.curr_pos,
                    paused,
                    adding_song,
                )
                stdscr.refresh()

        if next_song == -1:
            if i == scroller.pos:
                scroller.scroll_backward()
            i -= 1
        elif next_song == 1:
            if i == len(playlist) - 1:
                if loop:
                    next_next_playlist = next_playlist[:]
                    if reshuffle:
                        shuffle(next_next_playlist)
                    playlist, next_playlist = next_playlist, next_next_playlist
                    i = -1
                    scroller.pos = 0
                else:
                    # getch_manager.stop()
                    return
            else:
                if i == scroller.pos:
                    scroller.scroll_forward()
            i += 1


def print_entry(entry_list):
    """`entry_list` should be passed as a list (what you get when you call
    `line.split("|")`)."""
    click.secho(entry_list[0] + " ", fg="bright_black", nl=False)
    click.secho(entry_list[1], fg="blue", nl=(len(entry_list) == 2))
    if len(entry_list) > 2:
        click.echo(" " + ", ".join(entry_list[2].split(",")))


# endregion


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
def cli():
    """A command line interface for playing music."""
    if not os.path.exists(SONGS_DIR):
        os.makedirs(SONGS_DIR)
    if not os.path.exists(SONGS_INFO_PATH):
        with open(SONGS_INFO_PATH, "x", encoding="utf-8") as _:
            pass


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.argument("tags", nargs=-1)
@click.option(
    "-m",
    "--move",
    "move_",
    is_flag=True,
    help="Move file from PATH to maestro's internal song database instead of copying.",
)
@click.option(
    "-r",
    "--recursive",
    "recurse",
    is_flag=True,
    help="If PATH is a folder, add songs in subfolders.",
)
def add(path, tags, move_, recurse):
    """Add a new song, located at PATH. If PATH is a folder, adds all files
    in PATH (including files in subfolders if `-r` is passed). The name of each
    song will be the filename. Filenames and tags cannot contain the character
    '|', and tags cannot contain ','."""
    ext = os.path.splitext(path)[1]
    if not os.path.isdir(path) and ext not in EXTS:
        click.secho(f"'{ext}' is not supported", fg="red")
        return

    for tag in tags:
        if "," in tag or "|" in tag:
            click.secho("Tags cannot contain ',' or '|'", fg="red")
            return

    with open(SONGS_INFO_PATH, "a+", encoding="utf-8") as songs_file:
        songs_file.seek(0)  # start reading from beginning

        lines = songs_file.readlines()
        if not lines:
            song_id = 1
        else:
            song_id = int(lines[-1].split("|")[0]) + 1

        prepend_newline = lines and lines[-1][-1] != "\n"

        if os.path.isdir(path):
            if recurse:
                for dirpath, _, fnames in os.walk(path):
                    for fname in fnames:
                        if os.path.splitext(fname)[1] in EXTS:
                            if "|" in fname:
                                click.echo(
                                    f"Skipping {fname} because it contains '|'"
                                )
                                continue
                            _add(
                                os.path.join(dirpath, fname),
                                tags,
                                move_,
                                songs_file,
                                lines,
                                song_id,
                                prepend_newline,
                            )
                            prepend_newline = False
                            song_id += 1
            else:
                for fname in os.listdir(path):
                    if os.path.splitext(fname)[1] in EXTS:
                        if "|" in fname:
                            click.echo(
                                f"Skipping {fname} because it contains '|'"
                            )
                            continue
                        full_path = os.path.join(path, fname)
                        if os.path.isfile(full_path):
                            _add(
                                full_path,
                                tags,
                                move_,
                                songs_file,
                                lines,
                                song_id,
                                prepend_newline,
                            )
                            prepend_newline = False
                            song_id += 1
        else:
            if "|" in os.path.basename(path):
                click.secho("Filename cannot contain '|'", fg="red")
                return
            _add(
                path,
                tags,
                move_,
                songs_file,
                lines,
                song_id,
                prepend_newline,
            )


@cli.command(name="list")
@click.argument("search_tags", metavar="TAGS", nargs=-1)
def list_(search_tags):
    """List the entries for all songs.

    If TAGS are passed, any song matching any tag will be listed."""
    if search_tags:
        search_tags = set(search_tags)

    no_results = True
    with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
        for line in songs_file:
            details = line.strip().split("|")
            tags = set(details[2].split(","))
            if search_tags and not tags.intersection(search_tags):
                continue
            print_entry(details)
            no_results = False

    if no_results and search_tags:
        click.secho("No songs found matching tags", fg="red")


@cli.command()
@click.argument("ARGS", required=True, nargs=-1)
@click.option("-f", "--force", is_flag=True, help="Force deletion.")
@click.option(
    "-t",
    "--tag",
    is_flag=True,
    help="If passed, treat all arguments as tags, deleting every ocurrence of each tag.",
)
def remove(args, force, tag):
    """Remove either tag(s) or song(s) passed as ID(s)."""
    if not tag:
        try:
            song_ids = {int(song_id) for song_id in args}
        except ValueError:
            click.secho(
                "Song IDs must be integers. To delete tags, pass the '-t' flag.",
                fg="red",
            )
            return

        if not force:
            char = input(
                f"Are you sure you want to delete {len(song_ids)} song(s)? [y/n] "
            )

            if char.lower() != "y":
                print("Did not delete.")
                return

        with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
            lines = songs_file.read().splitlines()
            to_be_deleted = []
            for i in range(len(lines)):
                details = lines[i].strip().split("|")
                song_id = int(details[0])
                if song_id in song_ids:
                    to_be_deleted.append(i)

                    song_name = details[1]
                    os.remove(
                        os.path.join(SONGS_DIR, song_name)
                    )  # remove actual song

                    click.secho(
                        f"Removed song '{song_name}' with id {song_id}",
                        fg="green",
                    )
            for i in reversed(to_be_deleted):
                del lines[i]

        with open(SONGS_INFO_PATH, "w", encoding="utf-8") as songs_file:
            songs_file.write("\n".join(lines))
    else:
        tags_to_remove = set(args)
        if not force:
            char = input(
                f"Are you sure you want to delete {len(tags_to_remove)} tag(s)? [y/n] "
            )

            if char.lower() != "y":
                print("Did not delete.")
                return

        with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
            lines = songs_file.read().splitlines()
            for i in range(len(lines)):
                details = lines[i].strip().split("|")
                tags = details[2].split(",")
                for j in range(len(tags)):
                    if tags[j] in tags_to_remove:
                        del tags[j]
                details[2] = ",".join(tags)
                lines[i] = "|".join(details)

        with open(SONGS_INFO_PATH, "w", encoding="utf-8") as songs_file:
            songs_file.write("\n".join(lines))

        click.secho(
            f"Deleted all occurrences of {len(tags_to_remove)} tag(s)",
            fg="green",
        )


@cli.command(name="tag")
@click.argument("song_ids", type=click.INT, required=True, nargs=-1)
@click.option(
    "-t",
    "--tag",
    "tags",
    help="Tags to add.",
    multiple=True,
)
def tag_(song_ids, tags):
    """Add tags to a song (passed as ID). Tags cannot contain the characters
    ',' or '|'."""
    song_ids = set(song_ids)
    tags = set(tags)
    for tag in tags:
        if "," in tag or "|" in tag:
            click.secho("Tags cannot contain ',' or '|'", fg="red")
            return
    if tags:
        songs_file = open(SONGS_INFO_PATH, "r", encoding="utf-8")
        lines = songs_file.read().splitlines()
        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            if int(details[0]) in song_ids:
                if details[2]:
                    new_tags = details[2].split(",")
                else:
                    new_tags = []
                new_tags += [tag for tag in tags if tag not in new_tags]
                details[2] = ",".join(new_tags)
                lines[i] = "|".join(details)
        songs_file.close()

        songs_file = open(SONGS_INFO_PATH, "w", encoding="utf-8")
        songs_file.write("\n".join(lines))
        songs_file.close()

        click.secho(
            f"Added {len(tags)} tag(s) to {len(song_ids)} song(s)",
            fg="green",
        )
    else:
        click.secho("No tags passed", fg="red")


@cli.command()
@click.argument("song_ids", type=click.INT, required=True, nargs=-1)
@click.option(
    "-t",
    "--tag",
    "tags",
    help="Tags to remove.",
    multiple=True,
)
@click.option("-a", "--all", "all_", is_flag=True)
def untag(song_ids, tags, all_):
    """Remove tags from a specific song (passed as ID). Tags that the song
    doesn't have will be ignored.

    Passing the '-a/--all' flag will remove all tags from the song, unless TAGS
    is passed (in which case the flag is ignored)."""
    song_ids = set(song_ids)
    tags = set(tags)
    if tags:
        songs_file = open(SONGS_INFO_PATH, "r", encoding="utf-8")
        lines = songs_file.read().splitlines()
        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            if int(details[0]) in song_ids:
                tags_to_keep = [
                    tag for tag in details[2].split(",") if tag not in tags
                ]
                lines[i] = "|".join(details[:2] + [",".join(tags_to_keep)])
        songs_file.close()

        songs_file = open(SONGS_INFO_PATH, "w", encoding="utf-8")
        songs_file.write("\n".join(lines))
        songs_file.close()

        click.secho(
            f"Removed {len(tags)} tag(s) from {len(song_ids)} song(s)",
            fg="green",
        )
    else:
        if not all_:
            click.secho(
                "No tags passed—to remove all tags, pass the `-a/--all` flag",
                fg="red",
            )
        else:
            songs_file = open(SONGS_INFO_PATH, "r", encoding="utf-8")
            lines = songs_file.read().splitlines()
            for i in range(len(lines)):
                line = lines[i]
                details = line.strip().split("|")
                if int(details[0]) in song_ids:
                    lines[i] = "|".join(details[:2])
            songs_file.close()

            songs_file = open(SONGS_INFO_PATH, "w", encoding="utf-8")
            songs_file.write("\n".join(lines))
            songs_file.close()

            click.secho(
                f"Removed {len(tags)} tag(s) from {len(song_ids)} song(s)",
                fg="green",
            )


@cli.command()
@click.argument("tags", nargs=-1)
@click.option(
    "-s",
    "--shuffle",
    "shuffle_",
    is_flag=True,
    help="Randomize order of songs when played (if --loop is passed, only shuffles once, unless --reshuffle is also passed).",
)
@click.option(
    "-r",
    "--reverse",
    "reverse",
    is_flag=True,
    help="Play songs in reverse (most recently added first).",
)
@click.option(
    "-o",
    "--only",
    "only",
    type=click.INT,
    multiple=True,
    help="Play only this/these song(s) (can be passed multiple times, e.g. 'maestro play -o 1 -o 17').",
)
@click.option(
    "-v",
    "--volume",
    "volume",
    type=click.IntRange(0, 100),
    default=100,
    show_default=True,
)
@click.option("-l", "--loop", "loop", is_flag=True, help="Loop the playlist.")
@click.option(
    "-R",
    "--reshuffle",
    "reshuffle",
    is_flag=True,
    help="If --loop is passed, reshuffle the playlist once the last song of the first run-through has been played.",
)
@click.option(
    "-d",
    "--discord",
    "discord",
    is_flag=True,
    help="Discord rich presence. Ignored if required dependencies are not installed. Will fail silently and retry every time the song changes if Discord connection fails (e.g. Discord not open).",
)
def play(tags, shuffle_, reverse, only, volume, loop, reshuffle, discord):
    """Play your songs. If tags are passed, any song matching any tag will be in
    your playlist.

    \b
      SPACE  to pause
        b/p  to go (b)ack to (p)revious song
          r  to (r)eplay song
        s/n  to (s)kip to (n)ext song
       LEFT  to rewind 5s
      RIGHT  to fast forward 5s
          [  to decrease volume
          ]  to increase volume
          m  to (m)ute/unmute
        e/q  to (e)nd/(q)uit the song player
    UP/DOWN  to scroll through the playlist (changing selected song)
          d  to delete the selected (not necessarily currently playing!) song from the playlist
          a  to add a song (by ID) to the end of the playlist
    """
    playlist = []

    if only:
        only = set(only)
        with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
            for line in songs_file:
                details = line.strip().split("|")
                song_id = int(details[0])
                if song_id in only:
                    playlist.append(details)

        if not playlist:
            click.secho("No songs found with the given IDs", fg="red")
            return
    else:
        if not tags:
            with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
                for line in songs_file:
                    details = line.strip().split("|")
                    playlist.append(details)
        else:
            playlist = []
            with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
                for line in songs_file:
                    details = line.strip().split("|")
                    for tag in details[2].split(","):
                        if tag in tags:
                            playlist.append(details)
                            break

    if shuffle_:
        shuffle(playlist)
    elif reverse:
        playlist.reverse()

    if not playlist:
        click.secho("No songs found matching tag criteria", fg="red")
    else:
        volume /= 100
        curses.wrapper(
            _play,
            playlist,
            volume,
            loop,
            reshuffle,
            discord and can_update_discord,
        )


@cli.command()
@click.option(
    "-t",
    "--tag",
    "renaming_tag",
    is_flag=True,
    help="If passed, rename tag instead of song.",
)
@click.argument("original")
@click.argument("new_name")
def rename(original, new_name, renaming_tag):
    """Renames the song with the id ORIGINAL to NEW_NAME. The extension of the
    song (e.g. '.wav', '.mp3') is preserved—do not include it in the name.

    If the `-t/--tag` flag is passed, treats ORIGINAL as a tag, renaming it to
    NEW_NAME.
    """
    songs_file = open(SONGS_INFO_PATH, "r", encoding="utf-8")
    lines = songs_file.read().splitlines()
    if not renaming_tag:
        if not original.isnumeric():
            click.secho(
                "Song ID must be an integer. To rename a tag, pass the -t flag",
                fg="red",
            )
            return
        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            if int(details[0]) == original:
                old_name = details[1]
                details[1] = new_name + os.path.splitext(old_name)[1]

                lines[i] = "|".join(details)
                songs_file.close()
                songs_file = open(SONGS_INFO_PATH, "w", encoding="utf-8")
                songs_file.write("\n".join(lines))

                os.rename(
                    os.path.join(SONGS_DIR, old_name),
                    os.path.join(SONGS_DIR, details[1]),
                )

                click.secho(
                    f"Renamed song '{old_name}' with id {original} to '{details[1]}'",
                    fg="green",
                )

                break
        else:
            click.secho(f"Song with id {original} not found", fg="red")
            songs_file.close()
    else:
        original = original.lower()
        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            tags = details[2].split(",")
            for t in range(len(tags)):
                if tags[t] == original:
                    tags[t] = new_name
                    details[2] = ",".join(tags)

                    lines[i] = "|".join(details)
                    break

        songs_file.close()
        songs_file = open(SONGS_INFO_PATH, "w", encoding="utf-8")
        songs_file.write("\n".join(lines))

        click.secho(
            f"Replaced all ocurrences of tag '{original}' to '{new_name}'",
            fg="green",
        )


@cli.command()
@click.argument("phrase")
@click.option(
    "-t",
    "--tag",
    "searching_for_tags",
    is_flag=True,
    help="Searches for matching tags instead of song names.",
)
def search(phrase, searching_for_tags):
    """Searches for songs that contain PHRASE. All songs starting with PHRASE
    will appear before songs containing but not starting with PHRASE. This
    search is case-insensitive.

    If the `-t` flag is passed, searches for tags instead of song names."""
    phrase = phrase.lower()
    with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
        if not searching_for_tags:
            results = [], []  # starts, contains but does not start
            for line in songs_file:
                song_id, song_name, tags = line.strip().split("|")
                song_id = int(song_id)
                song_name = song_name.lower()

                if song_name.startswith(phrase):
                    results[0].append(song_id)
                elif phrase in song_name:
                    results[1].append(song_id)

            if not any(results):
                click.secho("No results found", fg="red")
                return

            songs_file.seek(0)
            for line in songs_file:
                details = line.strip().split("|")
                if int(details[0]) in results[0]:
                    print_entry(details)

            songs_file.seek(0)
            for line in songs_file:
                details = line.strip().split("|")
                if int(details[0]) in results[1]:
                    print_entry(details)

            click.secho(
                f"Found {len(results[0]) + len(results[1])} song(s)", fg="green"
            )
        else:
            results = set(), set()  # starts, contains but does not start
            for line in songs_file:
                song_id, song_name, tags = line.strip().split("|")
                tags = tags.split(",")

                for tag in tags:
                    tag_lower = tag.lower()
                    if tag_lower.startswith(phrase):
                        results[0].add(tag)
                    elif phrase in tag_lower:
                        results[1].add(tag)

            if not any(results):
                click.secho("No results found", fg="red")
                return

            for tag in results[0]:
                print(tag)

            for tag in results[1]:
                print(tag)

            click.secho(
                f"Found {len(results[0]) + len(results[1])} tag(s)", fg="green"
            )


@cli.command()
@click.argument("song_ids", type=click.INT, nargs=-1, required=True)
def entry(song_ids):
    """Prints the details of the song(s) with the id(s) SONG_IDS."""
    song_ids = set(song_ids)
    with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
        for line in songs_file:
            details = line.strip().split("|")
            if int(details[0]) in song_ids:
                print_entry(details)
