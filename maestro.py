# region imports
import curses
import multiprocessing
import os
import subprocess
import sys

import click

from collections import defaultdict
from queue import Queue
from random import shuffle, randint
from time import sleep, time

from icon import img

from just_playback import Playback
from tinytag import TinyTag

can_update_discord = True
try:
    import pypresence
except ImportError:
    can_update_discord = False

from helpers import *  # pylint: disable=wildcard-import,unused-wildcard-import

if sys.platform == "darwin":
    try:
        # pylint: disable=no-name-in-module,import-error
        from AppKit import (
            NSApplication,
            NSApp,
            NSObject,
            NSRunLoop,
            NSDate,
            NSApplicationActivationPolicyProhibited,
        )

        # from MediaPlayer import MPNowPlayingInfoPropertyElapsedPlaybackTime
        from PyObjCTools import AppHelper

        from mac_presence import MacNowPlaying

        # globals
        mac_now_playing = MacNowPlaying()
        cover_img = img

        can_mac_now_playing = True
    except Exception as e:  # pylint: disable=bare-except,broad-except
        # print(e, file=open("log.txt", "a"))
        can_mac_now_playing = False

# endregion

# region utility functions/classes


class AppDelegate(NSObject):  # so Python doesn't bounce in the dock
    def applicationDidFinishLaunching_(self, _aNotification):
        pass

    def sayHello_(self, _sender):
        pass


def app_helper_loop():
    # ns_application = NSApplication.sharedApplication()
    # logo_ns_image = NSImage.alloc().initByReferencingFile_(
    #     "./maestro_icon.png"
    # )
    # ns_application.setApplicationIconImage_(logo_ns_image)

    # # we must keep a reference to the delegate object ourselves,
    # # NSApp.setDelegate_() doesn't retain it. A local variable is
    # # enough here.
    # delegate = AppDelegate.alloc().init()
    # NSApp().setDelegate_(delegate)

    AppHelper.runEventLoop()


def discord_presence_loop(song_name_queue):
    try:
        discord_rpc = pypresence.Presence(client_id=1039038199881810040)
        discord_rpc.connect()
        discord_connected = True
    except:  # pylint: disable=bare-except
        discord_connected = False

    while True:
        song_name = ""
        if not song_name_queue.empty() or song_name:
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
                except:  # pylint: disable=bare-except
                    discord_connected = False
            else:
                try:
                    discord_rpc = pypresence.Presence(
                        client_id=1039038199881810040
                    )
                    discord_rpc.connect()
                    discord_connected = True
                except:  # pylint: disable=bare-except
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
                    except:  # pylint: disable=bare-except
                        discord_connected = False


def _play(stdscr, playlist, volume, loop, clip_mode, reshuffle, update_discord):
    global can_mac_now_playing  # pylint: disable=global-statement

    # region curses setup
    curses.start_color()
    curses.curs_set(False)
    curses.use_default_colors()
    stdscr.nodelay(True)
    curses.set_escdelay(25)  # 25 ms

    # region colors
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    if curses.can_change_color():
        curses.init_pair(2, curses.COLOR_BLACK + 8, -1)  # bright black
    else:
        curses.init_pair(2, curses.COLOR_BLACK, -1)
    curses.init_pair(3, curses.COLOR_BLUE, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_YELLOW, -1)
    curses.init_pair(6, curses.COLOR_GREEN, -1)
    curses.init_pair(7, curses.COLOR_MAGENTA, -1)
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
    curses.init_pair(17, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
    # endregion

    # endregion

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
        mac_now_playing.title = "maestro-cli"
        mac_now_playing.artist_queue = Queue()
        mac_now_playing.q = Queue()
        mac_now_playing.cover = cover_img

        ns_application = NSApplication.sharedApplication()
        # logo_ns_image = NSImage.alloc().initByReferencingFile_(
        #     "./maestro_icon.png"
        # )
        # ns_application.setApplicationIconImage_(logo_ns_image)
        ns_application.setActivationPolicy_(
            NSApplicationActivationPolicyProhibited
        )

        # NOTE: keep reference to delegate object, setDelegate_ doesn't retain
        delegate = AppDelegate.alloc().init()
        NSApp().setDelegate_(delegate)

        app_helper_process = multiprocessing.Process(
            daemon=True,
            target=app_helper_loop,
        )
        app_helper_process.start()

    prev_volume = volume

    player_output = PlayerOutput(stdscr, playlist, volume, clip_mode)
    while player_output.i in range(len(player_output.playlist)):
        player_output.paused = mac_now_playing.paused = False

        song_path = os.path.join(
            SONGS_DIR, player_output.playlist[player_output.i][1]
        )
        player_output.duration = full_duration = int(
            TinyTag.get(song_path).duration
        )

        clip_string = player_output.playlist[player_output.i][3]
        if clip_string:
            player_output.clip = tuple(
                map(float, player_output.playlist[player_output.i][3].split())
            )
        else:
            player_output.clip = 0, player_output.duration

        if sys.platform == "darwin" and can_mac_now_playing:
            mac_now_playing.pos = 0
            mac_now_playing.length = player_output.duration

            for c in player_output.playlist[player_output.i][1]:
                mac_now_playing.artist_queue.put(c)
            mac_now_playing.artist_queue.put("\n")

            update_now_playing = True

        if update_discord:
            for c in player_output.playlist[player_output.i][1]:
                discord_song_name_queue.put(c)
            discord_song_name_queue.put("\n")

        playback = Playback()
        playback.load_file(song_path)
        playback.play()
        start_time = pause_start = time()
        playback.set_volume(player_output.volume)

        player_output.output(playback.curr_pos)

        last_timestamp = playback.curr_pos
        next_song = 1  # -1 if going back, 0 if restarting, +1 if next song
        ending = False
        while True:
            if not playback.active or (
                player_output.clip_mode
                and playback.curr_pos > player_output.clip[1]
            ):
                next_song = not player_output.looping_current_song
                break

            if sys.platform == "darwin" and can_mac_now_playing:
                try:
                    if update_now_playing:
                        mac_now_playing.update()
                        update_now_playing = False
                    NSRunLoop.currentRunLoop().runUntilDate_(
                        NSDate.dateWithTimeIntervalSinceNow_(0.05)
                    )
                except:  # pylint: disable=bare-except
                    can_mac_now_playing = False

            if (
                sys.platform == "darwin"
                and can_mac_now_playing
                and not mac_now_playing.q.empty()
            ):
                c = mac_now_playing.q.get()
                if c in "nNsS":
                    if (
                        player_output.i == len(player_output.playlist) - 1
                        and not loop
                    ):
                        pass
                    else:
                        next_song = 1
                        playback.stop()
                        break
                elif c in "bBpP":
                    if player_output.i == 0:
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
                    ending = True
                    break
                elif c == " ":
                    player_output.paused = not player_output.paused

                    if player_output.paused:
                        playback.pause()
                        pause_start = time()
                    else:
                        playback.resume()
                        start_time += time() - pause_start

                    if sys.platform == "darwin" and can_mac_now_playing:
                        mac_now_playing.paused = player_output.paused
                        if player_output.paused:
                            mac_now_playing.pause()
                        else:
                            mac_now_playing.resume()
                        update_now_playing = True

                    player_output.output(playback.curr_pos)
            else:
                c = stdscr.getch()
                next_c = stdscr.getch()
                while next_c != -1:
                    c, next_c = next_c, stdscr.getch()

                if c != -1:
                    if player_output.adding_song is None:
                        if c == curses.KEY_LEFT:
                            playback.seek(playback.curr_pos - SCRUB_TIME)
                            if sys.platform == "darwin" and can_mac_now_playing:
                                mac_now_playing.pos = round(playback.curr_pos)
                                update_now_playing = True

                            last_timestamp = playback.curr_pos
                            player_output.output(playback.curr_pos)
                        elif c == curses.KEY_RIGHT:
                            playback.seek(playback.curr_pos + SCRUB_TIME)
                            if sys.platform == "darwin" and can_mac_now_playing:
                                mac_now_playing.pos = round(playback.curr_pos)
                                update_now_playing = True

                            last_timestamp = playback.curr_pos
                            player_output.output(playback.curr_pos)
                        elif c == curses.KEY_UP:
                            if player_output.scroller.pos != 0:
                                player_output.scroller.scroll_backward()
                                player_output.output(playback.curr_pos)
                        elif c == curses.KEY_DOWN:
                            if (
                                player_output.scroller.pos
                                != player_output.scroller.num_lines - 1
                            ):
                                player_output.scroller.scroll_forward()
                                player_output.output(playback.curr_pos)
                        elif c == curses.KEY_ENTER:
                            player_output.i = player_output.scroller.pos - 1
                            next_song = 1
                            playback.stop()
                            break
                        elif c == curses.KEY_RESIZE:
                            screen_size = stdscr.getmaxyx()
                            player_output.scroller.resize(screen_size[0] - 2)
                            player_output.output(playback.curr_pos)
                        else:
                            try:
                                c = chr(c)
                                if c in "nNsS":
                                    if (
                                        player_output.i
                                        == len(player_output.playlist) - 1
                                        and not loop
                                    ):
                                        pass
                                    else:
                                        next_song = 1
                                        playback.stop()
                                        break
                                elif c in "bBpP":
                                    if player_output.i == 0:
                                        pass
                                    else:
                                        next_song = -1
                                        playback.stop()
                                        break
                                elif c in "rR":
                                    playback.stop()
                                    next_song = 0
                                    break
                                elif c in "lL":
                                    player_output.looping_current_song = (
                                        not player_output.looping_current_song
                                    )
                                    player_output.output(playback.curr_pos)
                                elif c in "cC":
                                    player_output.clip_mode = (
                                        not player_output.clip_mode
                                    )
                                    if player_output.clip_mode:
                                        start, end = player_output.clip
                                        player_output.duration = end - start
                                        if (
                                            playback.curr_pos < start
                                            or playback.curr_pos > end
                                        ):
                                            playback.seek(start)
                                            if (
                                                sys.platform == "darwin"
                                                and can_mac_now_playing
                                            ):
                                                mac_now_playing.pos = round(
                                                    playback.curr_pos
                                                )
                                                update_now_playing = True
                                            last_timestamp = playback.curr_pos
                                    else:
                                        player_output.duration = full_duration
                                    player_output.output(playback.curr_pos)
                                elif c in "eEqQ":
                                    playback.stop()
                                    ending = True
                                    break
                                elif c in "dD":
                                    selected_song = player_output.scroller.pos
                                    del player_output.playlist[selected_song]
                                    player_output.scroller.num_lines -= 1
                                    if (
                                        selected_song == player_output.i
                                    ):  # deleted current song
                                        next_song = 1
                                        # will be incremented to i
                                        player_output.scroller.pos = (
                                            player_output.i - 1
                                        )
                                        player_output.i -= 1
                                        playback.stop()
                                        break
                                    # deleted song before current
                                    if selected_song < player_output.i:
                                        player_output.i -= 1
                                elif c in "aA":
                                    player_output.adding_song = "", 0
                                    curses.curs_set(True)
                                    screen_size = stdscr.getmaxyx()
                                    player_output.scroller.resize(
                                        screen_size[0] - 3
                                    )
                                    player_output.output(playback.curr_pos)
                                elif c in "mM":
                                    if player_output.volume == 0:
                                        player_output.volume = prev_volume
                                    else:
                                        player_output.volume = 0
                                    playback.set_volume(player_output.volume)

                                    player_output.output(playback.curr_pos)
                                elif c == " ":
                                    player_output.paused = (
                                        not player_output.paused
                                    )

                                    if player_output.paused:
                                        playback.pause()
                                        pause_start = time()
                                    else:
                                        playback.resume()
                                        start_time += time() - pause_start

                                    if (
                                        sys.platform == "darwin"
                                        and can_mac_now_playing
                                    ):
                                        mac_now_playing.paused = (
                                            player_output.paused
                                        )
                                        if player_output.paused:
                                            mac_now_playing.pause()
                                        else:
                                            mac_now_playing.resume()
                                        update_now_playing = True

                                    player_output.output(playback.curr_pos)
                                elif c == "[":
                                    player_output.volume = max(
                                        0, player_output.volume - VOLUME_STEP
                                    )
                                    playback.set_volume(player_output.volume)

                                    player_output.output(playback.curr_pos)

                                    prev_volume = player_output.volume
                                elif c == "]":
                                    player_output.volume = min(
                                        1, player_output.volume + VOLUME_STEP
                                    )
                                    playback.set_volume(player_output.volume)

                                    player_output.output(playback.curr_pos)

                                    prev_volume = player_output.volume
                                elif c in "\r\n":
                                    player_output.i = (
                                        player_output.scroller.pos - 1
                                    )
                                    next_song = 1
                                    playback.stop()
                                    break
                            except (ValueError, OverflowError):
                                pass
                    else:
                        if c == curses.KEY_RESIZE:
                            screen_size = stdscr.getmaxyx()
                            player_output.scroller.resize(screen_size[0] - 3)
                            player_output.output(playback.curr_pos)
                        elif c == curses.KEY_LEFT:
                            # pylint: disable=unsubscriptable-object
                            player_output.adding_song = (
                                player_output.adding_song[0],
                                max(player_output.adding_song[1] - 1, 0),
                            )
                            player_output.output(playback.curr_pos)
                        elif c == curses.KEY_RIGHT:
                            # pylint: disable=unsubscriptable-object
                            player_output.adding_song = (
                                player_output.adding_song[0],
                                min(
                                    player_output.adding_song[1] + 1,
                                    len(player_output.adding_song[0]),
                                ),
                            )
                            player_output.output(playback.curr_pos)
                        elif c == curses.KEY_UP:
                            if player_output.scroller.pos != 0:
                                player_output.scroller.scroll_backward()
                                player_output.output(playback.curr_pos)
                        elif c == curses.KEY_DOWN:
                            if (
                                player_output.scroller.pos
                                != player_output.scroller.num_lines - 1
                            ):
                                player_output.scroller.scroll_forward()
                                player_output.output(playback.curr_pos)
                        elif c == curses.KEY_DC:
                            # pylint: disable=unsubscriptable-object
                            if player_output.adding_song[1] > 0:
                                player_output.adding_song = (
                                    player_output.adding_song[0][
                                        : player_output.adding_song[1] - 1
                                    ]
                                    + player_output.adding_song[0][
                                        player_output.adding_song[1] :
                                    ],
                                    player_output.adding_song[1] - 1,
                                )
                            player_output.output(playback.curr_pos)
                        elif c == curses.KEY_ENTER:
                            # pylint: disable=unsubscriptable-object
                            if player_output.adding_song[0].isnumeric():
                                for details in player_output.playlist:
                                    if int(details[0]) == int(
                                        player_output.adding_song[0]
                                    ):
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
                                            if song_id == int(
                                                player_output.adding_song[0]
                                            ):
                                                player_output.playlist.append(
                                                    details
                                                )
                                                if (
                                                    player_output.looping_current_song
                                                ):
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
                                                player_output.scroller.num_lines += (
                                                    1
                                                )
                                                player_output.adding_song = None
                                                curses.curs_set(False)
                                                player_output.scroller.resize(
                                                    screen_size[0] - 2
                                                )
                                                player_output.output(
                                                    playback.curr_pos
                                                )
                                                break
                        elif c == 27:  # ESC key
                            player_output.adding_song = None
                            curses.curs_set(False)
                            player_output.scroller.resize(screen_size[0] - 2)
                            player_output.output(playback.curr_pos)
                        else:
                            try:
                                c = chr(c)
                                if c in "\r\n":
                                    # pylint: disable=unsubscriptable-object
                                    if player_output.adding_song[0].isnumeric():
                                        for details in player_output.playlist:
                                            if int(details[0]) == int(
                                                player_output.adding_song[0]
                                            ):
                                                break
                                        else:
                                            with open(
                                                SONGS_INFO_PATH,
                                                "r",
                                                encoding="utf-8",
                                            ) as songs_file:
                                                for line in songs_file:
                                                    details = (
                                                        line.strip().split("|")
                                                    )
                                                    song_id = int(details[0])
                                                    if song_id == int(
                                                        player_output.adding_song[
                                                            0
                                                        ]
                                                    ):
                                                        player_output.playlist.append(
                                                            details
                                                        )
                                                        if (
                                                            player_output.looping_current_song
                                                        ):
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
                                                        player_output.scroller.num_lines += (
                                                            1
                                                        )
                                                        player_output.adding_song = (
                                                            None
                                                        )
                                                        curses.curs_set(False)
                                                        player_output.scroller.resize(
                                                            screen_size[0] - 2
                                                        )
                                                        player_output.output(
                                                            playback.curr_pos
                                                        )
                                                        break
                                elif c in "\b\x7f":
                                    # pylint: disable=unsubscriptable-object
                                    if player_output.adding_song[1] > 0:
                                        player_output.adding_song = (
                                            player_output.adding_song[0][
                                                : player_output.adding_song[1]
                                                - 1
                                            ]
                                            + player_output.adding_song[0][
                                                player_output.adding_song[1] :
                                            ],
                                            player_output.adding_song[1] - 1,
                                        )
                                    player_output.output(playback.curr_pos)
                                else:
                                    player_output.adding_song = (
                                        # pylint: disable=unsubscriptable-object
                                        player_output.adding_song[0][
                                            : player_output.adding_song[1]
                                        ]
                                        + c
                                        + player_output.adding_song[0][
                                            player_output.adding_song[1] :
                                        ],
                                        player_output.adding_song[1] + 1,
                                    )
                                    player_output.output(playback.curr_pos)
                            except (ValueError, OverflowError):
                                pass

            if sys.platform == "darwin" and can_mac_now_playing:
                if abs(mac_now_playing.pos - playback.curr_pos) > 2:
                    playback.seek(mac_now_playing.pos)
                    last_timestamp = mac_now_playing.pos
                    update_now_playing = True
                    player_output.output(playback.curr_pos)
                else:
                    mac_now_playing.pos = round(playback.curr_pos)

            progress_bar_width = stdscr.getmaxyx()[1] - 18
            frame_duration = min(
                (
                    1
                    if progress_bar_width < MIN_PROGRESS_BAR_WIDTH
                    else player_output.duration / (progress_bar_width * 8)
                ),
                1,
            )
            if abs(playback.curr_pos - last_timestamp) > frame_duration:
                last_timestamp = playback.curr_pos
                player_output.output(playback.curr_pos)

        time_listened = time() - start_time
        if player_output.paused:
            time_listened -= time() - pause_start

        with open(TOTAL_STATS_PATH, "r+", encoding="utf-8") as playlist_file:
            lines = playlist_file.readlines()
            for j in range(len(lines)):
                song_id, listened = lines[j].strip().split("|")
                if song_id == player_output.playlist[player_output.i][0]:
                    listened = float(listened) + time_listened
                    lines[j] = f"{song_id}|{listened}\n"
                    break

            # write out
            playlist_file.seek(0)
            playlist_file.write("".join(lines))
            playlist_file.truncate()

        with open(CUR_YEAR_STATS_PATH, "r+", encoding="utf-8") as playlist_file:
            lines = playlist_file.readlines()
            for j in range(len(lines)):
                song_id, listened = lines[j].strip().split("|")
                if song_id == player_output.playlist[player_output.i][0]:
                    listened = float(listened) + time_listened
                    lines[j] = f"{song_id}|{listened}\n"
                    break

            # write out
            playlist_file.seek(0)
            playlist_file.write("".join(lines))
            playlist_file.truncate()

        if ending:
            return

        if next_song == -1:
            if player_output.i == player_output.scroller.pos:
                player_output.scroller.scroll_backward()
            player_output.i -= 1
        elif next_song == 1:
            if player_output.i == len(player_output.playlist) - 1:
                if loop:
                    next_next_playlist = next_playlist[:]
                    if reshuffle:
                        shuffle(next_next_playlist)
                    player_output.playlist, next_playlist = (
                        next_playlist,
                        next_next_playlist,
                    )
                    player_output.i = -1
                    player_output.scroller.pos = 0
                else:
                    return
            else:
                if player_output.i == player_output.scroller.pos:
                    player_output.scroller.scroll_forward()
            player_output.i += 1


# endregion


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
def cli():
    """A command line interface for playing music."""
    if not os.path.exists(SONGS_DIR):
        os.makedirs(SONGS_DIR)
    if not os.path.exists(SONGS_INFO_PATH):
        with open(SONGS_INFO_PATH, "x", encoding="utf-8") as _:
            pass

    if not os.path.exists(STATS_DIR):
        os.makedirs(STATS_DIR)
    if not os.path.exists(TOTAL_STATS_PATH):
        with open(TOTAL_STATS_PATH, "x", encoding="utf-8") as _:
            pass
    if not os.path.exists(CUR_YEAR_STATS_PATH):
        with open(CUR_YEAR_STATS_PATH, "x", encoding="utf-8") as _:
            pass


@cli.command()
@click.argument("path_", metavar="PATH_OR_URL")
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
@click.option(
    "-u",
    "--url",
    is_flag=True,
    help="Add a song from a YouTube or YouTube Music URL.",
)
@click.option(
    "-f",
    "--format",
    "format_",
    type=click.Choice(
        [
            "wav",
            "mp3",
            "flac",
            "ogg",
        ]
    ),
    help="Specify the format of the song if downloading.",
    default="wav",
    show_default=True,
)
@click.option(
    "-c",
    "--clip",
    nargs=2,
    type=float,
    help="Add a clip.",
)
@click.option(
    "-p",
    "--playlist",
    "playlist_",
    is_flag=True,
    help="If song URL passed is from a playlist, download all the songs. If the URL points directly to a playlist, this flag is unncessary.",
)
def add(path_, tags, move_, recurse, url, format_, clip, playlist_):
    """Add a new song, located at PATH. If PATH is a folder, adds all files
    in PATH (including files in subfolders if `-r` is passed). The name of each
    song will be the filename. Filenames and tags cannot contain the character
    '|', and tags cannot contain ','.

    If the '-u' or '--url' flag is passed, PATH is treated as a YouTube or
    YouTube Music URL instead of a file path.

    Unlike `maestro clip`, you cannot pass only the start time and not the end.
    To get around this, you can pass -1 as the end time."""

    paths = None
    if not url and not os.path.exists(path_):
        click.secho(
            f"The path '{path_}' does not exist. To download from a YouTube or YouTube Music URl, pass the '-u/--url' flag.",
            fg="red",
        )
        return
    elif url:
        try:
            subprocess.run(
                [
                    "yt-dlp",
                    path_,
                    "-x",
                    "--audio-format",
                    format_,
                    "--no-playlist" if not playlist_ else "",
                    "-o",
                    os.path.join(MAESTRO_DIR, "%(title)s.%(ext)s"),
                ],
                check=True,
            )
        except subprocess.CalledProcessError:
            click.echo(
                "yt-dlp not found ... trying youtube-dl instead",
            )
            try:
                subprocess.run(
                    [
                        "youtube-dl",
                        path_,
                        "-x",
                        "--audio-format",
                        format_,
                        "--no-playlist" if not playlist_ else "",
                        "-o",
                        os.path.join(MAESTRO_DIR, "%(title)s.%(ext)s"),
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError:
                click.secho(
                    "Neither yt-dlp nor youtube-dl is installed. Please install one of them and try again.",
                )
                return

        paths = []
        for fname in os.listdir(MAESTRO_DIR):
            if fname.endswith(format_):
                raw_path = os.path.join(MAESTRO_DIR, fname)
                sanitized_path = raw_path.replace("|", "-")

                os.rename(raw_path, sanitized_path)
                paths.append(sanitized_path)

        move_ = True

    if paths is None:
        paths = [path_]

    for path in paths:
        if clip is not None:
            song_duration = TinyTag.get(path).duration

            start, end = clip
            if start < 0:
                click.secho("Clip start time cannot be negative", fg="red")
                return
            elif start > song_duration:
                click.secho(
                    "Clip start time cannot be greater than the song duration",
                    fg="red",
                )
                return

            if end == -1:
                end = song_duration
            elif end < start:
                click.secho(
                    "Clip end time cannot be less than the clip start time",
                    fg="red",
                )
                return
            elif end > song_duration:
                click.secho(
                    "Clip end time cannot be greater than the song duration",
                    fg="red",
                )
                return
        else:
            start = end = None

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
                                add_song(
                                    os.path.join(dirpath, fname),
                                    tags,
                                    move_,
                                    songs_file,
                                    lines,
                                    song_id,
                                    prepend_newline,
                                    start,
                                    end,
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
                                add_song(
                                    full_path,
                                    tags,
                                    move_,
                                    songs_file,
                                    lines,
                                    song_id,
                                    prepend_newline,
                                    start,
                                    end,
                                )
                                prepend_newline = False
                                song_id += 1
            else:
                if "|" in os.path.basename(path):
                    click.secho("Filename cannot contain '|'", fg="red")
                    return
                add_song(
                    path,
                    tags,
                    move_,
                    songs_file,
                    lines,
                    song_id,
                    prepend_newline,
                    start,
                    end,
                )


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
                "Song IDs must be integers. To delete tags, pass the '-t/--tag' flag.",
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

        with (
            open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file,
            open(TOTAL_STATS_PATH, "r", encoding="utf-8") as total_stats_file,
            open(
                CUR_YEAR_STATS_PATH, "r", encoding="utf-8"
            ) as cur_year_stats_file,
        ):
            lines = songs_file.read().splitlines()
            total_stats_lines = total_stats_file.read().splitlines()
            cur_year_stats_lines = cur_year_stats_file.read().splitlines()

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
                        f"Removed song '{song_name}' with ID {song_id}",
                        fg="green",
                    )

            for i in reversed(to_be_deleted):
                del lines[i]
                del total_stats_lines[i]
                del cur_year_stats_lines[i]

        with (
            open(SONGS_INFO_PATH, "w", encoding="utf-8") as songs_file,
            open(TOTAL_STATS_PATH, "w", encoding="utf-8") as total_stats_file,
            open(
                CUR_YEAR_STATS_PATH, "w", encoding="utf-8"
            ) as cur_year_stats_file,
        ):
            songs_file.write("\n".join(lines))
            total_stats_file.write("\n".join(total_stats_lines))
            cur_year_stats_file.write("\n".join(cur_year_stats_lines))
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
                lines[i] = "|".join(
                    details[:2] + [",".join(tags_to_keep)] + details[3:]
                )
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
                    lines[i] = "|".join(details[:2] + [""] + details[3:])
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
    "-c", "--clips", "clips", is_flag=True, help="Start in clip mode."
)
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
@click.option(
    "-m",
    "--match-all",
    "match_all",
    is_flag=True,
    help="Play songs that match all tags, not any.",
)
def play(
    tags,
    shuffle_,
    reverse,
    only,
    volume,
    loop,
    clips,
    reshuffle,
    discord,
    match_all,
):
    """Play your songs. If tags are passed, any song matching any tag will be in
    your playlist.

    \b
      SPACE  to pause/play
        b/p  to go (b)ack to (p)revious song
          r  to (r)eplay song
        s/n  to (s)kip to (n)ext song
          l  to (l)oop the current song
          c  to toggle (c)lip mode
       LEFT  to rewind 5s
      RIGHT  to fast forward 5s
          [  to decrease volume
          ]  to increase volume
          m  to (m)ute/unmute
        e/q  to (e)nd/(q)uit the song player
    UP/DOWN  to scroll through the playlist (mouse scrolling should also work)
          d  to delete the selected (not necessarily currently playing!) song from the playlist
          a  to add a song (by ID) to the end of the playlist

    \b
    song color indicates mode:
        \x1b[1;34mblue\x1b[0m     normal
        \x1b[1;33myellow\x1b[0m   looping current song

    \b
    progress bar color indicates status:
        \x1b[1;33myellow\x1b[0m   normal
        \x1b[1;35mmagenta\x1b[0m  playing clip
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
            tags = set(tags)
            playlist = []
            with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
                for line in songs_file:
                    details = line.strip().split("|")
                    song_tags = set(details[2].split(","))
                    if not match_all:
                        if tags & song_tags:  # intersection
                            playlist.append(details)
                    else:
                        if tags <= song_tags:  # subset
                            playlist.append(details)

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
            clips,
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
    """Renames the song with the ID ORIGINAL to NEW_NAME. The extension of the
    song (e.g. '.wav', '.mp3') is preserved—do not include it in the name.

    If the `-t/--tag` flag is passed, treats ORIGINAL as a tag, renaming all
    ocurrences of it to NEW_NAME.
    """
    songs_file = open(SONGS_INFO_PATH, "r", encoding="utf-8")
    lines = songs_file.read().splitlines()
    if not renaming_tag:
        if not original.isnumeric():
            click.secho(
                "Song ID must be an integer. To rename a tag, pass the '-t/--tag' flag",
                fg="red",
            )
            return
        original = int(original)
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
                    f"Renamed song '{old_name}' with ID {original} to '{details[1]}'",
                    fg="green",
                )

                break
        else:
            click.secho(f"Song with ID {original} not found", fg="red")
            songs_file.close()
    else:
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
                song_id, song_name, tags, *_ = line.strip().split("|")
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
                song_id, song_name, tags, *_ = line.strip().split("|")
                if tags:
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


@cli.command(name="list")
@click.argument("search_tags", metavar="TAGS", nargs=-1)
@click.option(
    "-s",
    "--sort",
    "sort_",
    type=click.Choice(
        (
            "id",
            "name",
            "n",
            "listen-time",
            "listen_time",
            "l",
            "duration",
            "d",
            "times-listened",
            "times_listened",
            "t",
        )
    ),
    help="Sort by ID, name, seconds listened, or times listened (seconds/song duration). Greatest first.",
    default="id",
    show_default=True,
)
@click.option(
    "-r",
    "--reverse",
    "reverse_",
    is_flag=True,
    help="Reverse the sorting order (greatest first).",
)
@click.option(
    "-t",
    "--tag",
    "listing_tags",
    is_flag=True,
    help="List tags matching TAGS.",
)
@click.option(
    "-y",
    "--year",
    "year",
    help="Show time listened for a specific year, instead of the total. Passing 'cur' will show the time listened for the current year.",
)
@click.option("-T", "--top", "top", type=int, help="Show the top n songs/tags.")
@click.option(
    "-m",
    "--match-all",
    "match_all",
    is_flag=True,
    help="Shows songs that match all tags instead of any tag. Ignored if '-t/--tag' is passed.",
)
def list_(search_tags, listing_tags, year, sort_, top, reverse_, match_all):
    """List the entries for all songs.

    Output format: ID, name, duration, listen time, times listened, [clip-start, clip-end] if clip exists, comma-separated tags if any

    If the `-t` flag is passed, tags will be listed instead of songs.

    Output format: tag, duration, listen time, times listened

    If TAGS are passed, any tag/song matching any tag in TAGS will be listed.
    """
    if top is not None:
        if top < 1:
            click.secho(
                "The option `--top` must be a positive number", fg="red"
            )
            return

    if year is None:
        stats_path = TOTAL_STATS_PATH
    else:
        if year == "cur":
            year = CUR_YEAR
            stats_path = CUR_YEAR_STATS_PATH
        else:
            if not year.isdigit():
                click.secho("Year must be a number or 'cur'", fg="red")
                return
            stats_path = os.path.join(STATS_DIR, f"{year}.txt")

    if search_tags:
        search_tags = set(search_tags)

    num_lines = 0

    if listing_tags:
        with (
            open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file,
            open(stats_path, "r", encoding="utf-8") as stats_file,
        ):
            tags = defaultdict(lambda: (0.0, 0.0))

            songs_lines = songs_file.readlines()
            stats_lines = stats_file.readlines()
            for i in range(len(songs_lines)):
                song_name, tag_string = songs_lines[i].strip().split("|")[1:3]
                if tag_string:
                    for tag in tag_string.split(","):
                        if not search_tags or tag in search_tags:
                            tags[tag] = (
                                tags[tag][0]
                                + float(stats_lines[i].strip().split("|")[1]),
                                tags[tag][1]
                                + TinyTag.get(
                                    os.path.join(SONGS_DIR, song_name)
                                ).duration,
                            )

            for tag, (listen_time, total_duration) in tags.items():
                click.echo(
                    f"{tag} {click.style(format_seconds(total_duration, show_decimal=True), fg='bright_black')} {click.style(format_seconds(listen_time, show_decimal=True), fg='yellow')} {click.style('%.2f'%(listen_time/total_duration), fg='bright_black')}"
                )
                num_lines += 1
                if top is not None and num_lines == top:
                    break
        return

    no_results = True
    with (
        open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file,
        open(stats_path, "r", encoding="utf-8") as stats_file,
    ):
        lines = songs_file.readlines()
        stats = stats_file.readlines()
        for i in range(len(lines)):
            details = lines[i].strip().split("|")

            tags = set(details[2].split(","))
            if search_tags:
                if match_all:
                    if not search_tags <= tags:  # subset
                        lines[i] = ""
                        continue
                else:
                    if not search_tags & tags:  # intersection
                        lines[i] = ""
                        continue

            time_listened = stats[i].strip().split("|")[1]
            lines[i] = tuple(details) + (
                time_listened,
                TinyTag.get(os.path.join(SONGS_DIR, details[1])).duration,
            )

        lines = [line for line in lines if line]

        if sort_ == "id":
            sort_key = lambda t: int(t[0])
        elif sort_ in ("name", "n"):
            sort_key = lambda t: t[1]
        elif sort_ in ("listen-time", "listen_time", "l"):
            sort_key = lambda t: float(t[-2])
        elif sort_ in ("duration", "d"):
            sort_key = lambda t: float(t[-1])
        elif sort_ in ("times-listened", "times_listened", "t"):
            sort_key = lambda t: float(t[-2]) / float(t[-1])
        lines.sort(
            key=sort_key,
            reverse=not reverse_,
        )

        for details in lines:
            print_entry(details)
            num_lines += 1
            no_results = False
            if top is not None and num_lines == top:
                break

    if no_results and search_tags:
        click.secho("No songs found matching tags", fg="red")
    elif no_results:
        click.secho(
            "No songs found. Use `maestro add` to add a song.", fg="red"
        )


@cli.command()
@click.option(
    "-y",
    "--year",
    "year",
    help="Show time listened for a specific year, instead of the total. Passing 'cur' will show the time listened for the current year.",
)
@click.argument("song_ids", type=click.INT, nargs=-1, required=True)
def entry(song_ids, year):
    """Prints the details of the song(s) with the ID(s) SONG_IDS.

    Output format: ID, name, duration, listen time, times listened, [clip-start, clip-end] if clip exists, comma-separated tags if any"""
    song_ids = set(song_ids)

    if year is None:
        stats_path = TOTAL_STATS_PATH
    else:
        if year == "cur":
            year = CUR_YEAR
            stats_path = CUR_YEAR_STATS_PATH
        else:
            if not year.isdigit():
                click.secho("Year must be a number", fg="red")
                return
            stats_path = os.path.join(STATS_DIR, f"{year}.txt")

    try:
        with (
            open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file,
            open(stats_path, "r", encoding="utf-8") as stats_file,
        ):
            lines = songs_file.readlines()
            stats_lines = stats_file.readlines()
            for i in range(len(lines)):
                details = lines[i].strip().split("|")
                if int(details[0]) in song_ids:
                    print_entry(
                        details
                        + stats_lines[i].strip().split("|")[1:2]
                        + [
                            TinyTag.get(
                                os.path.join(SONGS_DIR, details[1])
                            ).duration
                        ]
                    )
                    song_ids.remove(int(details[0]))
    except FileNotFoundError:
        click.secho(f"No stats found for year {year}", fg="red")

    if song_ids:
        song_ids = [str(id_) for id_ in song_ids]
        click.secho(f"No songs found with IDs: {', '.join(song_ids)}", fg="red")


@cli.command()
@click.argument("song", required=True)
@click.option(
    "-t",
    "--title",
    "title",
    is_flag=True,
    help="Treat SONG as a song title instead of an ID.",
)
def recommend(song, title):
    """Recommends songs (possibly explicit) using the YouTube Music API similar
    to the song with ID SONG to listen to.

    If the `-t` flag is passed, SONG is treated as a song title to search for
    on YouTube Music."""
    try:
        from ytmusicapi import YTMusic
    except ImportError:
        click.secho(
            "The `recommend` command requires the `ytmusicapi` package to be installed. Run `pip install ytmusicapi` to install it.",
            fg="red",
        )
        return

    ytmusic = YTMusic()

    if title:
        results = ytmusic.search(song, filter="songs")
    else:
        if not song.isdigit():
            click.secho(
                "Song ID must be a number. To get recommendations by title, pass the '-t/--title' flag.",
                fg="red",
            )
            return

        with open(SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
            for line in songs_file:
                details = line.strip().split("|")
                if details[0] == song:
                    results = ytmusic.search(
                        os.path.splitext(details[1])[0], filter="songs"
                    )
                    break
            else:
                click.secho(f"No song found with ID {song}", fg="red")
                return

    yt_music_playlist = ytmusic.get_watch_playlist(results[0]["videoId"])

    click.echo("Recommendations for ", nl=False)
    click.secho(
        yt_music_playlist["tracks"][0]["title"] + " ",
        fg="blue",
        nl=False,
    )
    click.secho(
        f"(https://music.youtube.com/watch?v={yt_music_playlist['tracks'][0]['videoId']})",
        fg="bright_black",
        nl=False,
    )
    click.echo(":")
    for track in yt_music_playlist["tracks"][1:]:
        click.secho(track["title"] + " ", fg="blue", bold=True, nl=False)
        click.secho(
            "https://music.youtube.com/watch?v=", fg="bright_black", nl=False
        )
        click.secho(track["videoId"], fg="bright_black", bold=True)


@cli.command()
@click.argument("song_ids", required=True, type=int, nargs=-1)
@click.option("-b", "--bottom", "bottom", is_flag=True)
def push(song_ids, bottom):
    """
    Push the song(s) with ID(s) SONG_IDS to the top of the playlist (as if they
    were the songs most recently added) in the order they are passed (e.g.
    `maestro push 1 2 3` will make the most recent song be 3).

    If the `-b` flag is passed, the song(s) will be pushed to the bottom of the
    list instead.
    """
    with open(SONGS_INFO_PATH, "r+", encoding="utf-8") as songs_file:
        lines = songs_file.readlines()

        for song_id in song_ids:
            for i in range(len(lines)):
                if lines[i].startswith(str(song_id)):
                    break
            else:
                click.secho(f"No song found with ID {song_id}", fg="red")
                return

            if not bottom:
                lines.append(lines.pop(i))
            else:
                lines.insert(0, lines.pop(i))

        songs_file.seek(0)
        songs_file.write("".join(lines))
        songs_file.truncate()


@cli.command(name="clip")
@click.argument("song_id", required=True, type=int)
@click.argument("start", required=True, type=float)
@click.argument("end", required=False, type=float, default=None)
def clip_(song_id, start, end):
    """
    Sets the clip for the song with ID SONG_ID to the time range START to END
    (in seconds).

    If END is not passed, the clip will be from START to the end of the song.
    """
    if start < 0:
        click.secho("START must be a positive number.", fg="red")
        return
    if end is not None and end < 0:
        click.secho("END must be a positive number.", fg="red")
        return

    with open(SONGS_INFO_PATH, "r+", encoding="utf-8") as songs_file:
        lines = songs_file.readlines()

        for i in range(len(lines)):
            if lines[i].startswith(str(song_id)):
                break
        else:
            click.secho(f"No song found with ID {song_id}", fg="red")
            return

        details = lines[i].strip().split("|")

        duration = TinyTag.get(os.path.join(SONGS_DIR, details[1])).duration
        if end is None:
            end = duration
            if start > end:
                click.secho(
                    "START must be less than the song duration.", fg="red"
                )
                return
        if start > end:
            click.secho("START must be less than END.", fg="red")
            return

        lines[i] = (
            "|".join(details[:3] + [str(start) + " " + str(end)] + details[5:])
            + "\n"
        )

        songs_file.seek(0)
        songs_file.write("".join(lines))
        songs_file.truncate()


@cli.command()
@click.argument("song_ids", type=int, nargs=-1, required=False)
@click.option(
    "-a",
    "--all",
    "all_",
    is_flag=True,
    help="Remove clips for all songs. Ignores SONG_IDS.",
)
@click.option("-f", "--force", "force", is_flag=True)
def unclip(song_ids, all_, force):
    """
    Removes clip for the song(s) with ID(s) SONG_IDS.

    If the `-a/--all` flag is passed, the clips for all songs will be removed,
    ignoring SONG_IDS. This prompts for confirmation unless the `-f/--force`
    flag is passed.
    """
    if not all_:
        if song_ids:
            song_ids = set(song_ids)
        else:
            click.secho(
                "No song IDs passed. To remove clips for all songs, pass the '-a/--all' flag.",
                fg="red",
            )
            return

    if all_ and not force:
        click.echo(
            "Are you sure you want to remove clips for all songs? This cannot be undone. [y/n] ",
        )
        if input().lower() != "y":
            return

    with open(SONGS_INFO_PATH, "r+", encoding="utf-8") as songs_file:
        lines = songs_file.readlines()

        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            if all_ or int(details[0]) in song_ids:
                lines[i] = "|".join(details[:3] + [""] + details[5:]) + "\n"

        songs_file.seek(0)
        songs_file.write("".join(lines))
        songs_file.truncate()

    if all_:
        click.secho("Removed clips for all songs.", fg="green")
    else:
        click.secho(
            f"Removed clip(s) for song(s) with ID(s) {', '.join(map(str, song_ids))}.",
            fg="green",
        )
