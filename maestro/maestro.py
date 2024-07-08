# region imports
import curses
import json
import multiprocessing
import os
import requests
import subprocess
import sys

import click
import keyring
import music_tag

from collections import defaultdict
from queue import Queue
from random import randint
from shutil import move, copy
from time import sleep, time

from maestro.icon import img
from maestro.__version__ import VERSION

from just_playback import Playback
from yt_dlp import YoutubeDL

# import gui_helper

can_update_discord = True
try:
    import pypresence
except ImportError:
    can_update_discord = False

can_mac_now_playing = False
if sys.platform == "darwin":
    try:
        # pylint: disable=no-name-in-module,import-error
        from AppKit import (
            NSApp,
            NSApplication,
            # NSApplicationDelegate,
            NSApplicationActivationPolicyProhibited,
            NSDate,
            NSObject,
            NSRunLoop,
        )

        # from MediaPlayer import MPNowPlayingInfoPropertyElapsedPlaybackTime
        from PyObjCTools import AppHelper

        from maestro.mac_presence import MacNowPlaying

        # globals
        mac_now_playing = MacNowPlaying()
        cover_img = img
        can_mac_now_playing = True
    except (
        Exception  # pylint: disable=bare-except,broad-except
    ) as mac_import_err:
        pass

from maestro import config
from maestro import helpers

from maestro.helpers import print_to_logfile  # pylint: disable=unused-import

# endregion

# region utility functions/classes

if can_mac_now_playing:

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


def read_from_queue(queue):
    res = ""
    while not queue.empty():
        res = ""
        c = queue.get()
        while c != "\n":
            res += c
            c = queue.get()

    return res


def discord_presence_loop(
    song_name_queue,
    artist_queue,
    album_queue,
    discord_connected,
    stream_username,
):
    try:
        discord_rpc = pypresence.Presence(client_id=config.DISCORD_ID)
        discord_rpc.connect()
        discord_connected.value = 1
    except Exception as e:  # pylint: disable=broad-except,unused-variable
        # print_to_logfile(e)
        discord_connected.value = 0

    while True:
        song_name = ""
        if not song_name_queue.empty() or song_name:
            song_name = read_from_queue(song_name_queue)
            artist_name = "by " + read_from_queue(artist_queue)
            album_name = read_from_queue(album_queue)

            if discord_connected.value:
                try:
                    discord_rpc.update(
                        details=song_name,
                        state=artist_name,
                        large_image=f"{config.MAESTRO_SITE}/api/get_artwork?mount={stream_username}",
                        large_text=album_name,
                        buttons=(
                            [
                                {
                                    "label": "Listen Along",
                                    "url": f"{config.MAESTRO_SITE}/listen/{stream_username}",
                                }
                            ]
                            if stream_username
                            else []
                        ),
                    )
                    song_name = ""
                    artist_name = ""
                    album_name = ""
                    sleep(15)
                except:  # pylint: disable=bare-except
                    discord_connected.value = 0
            else:
                try:
                    discord_rpc = pypresence.Presence(
                        client_id=config.DISCORD_ID
                    )
                    discord_rpc.connect()
                    discord_connected.value = 1
                except:  # pylint: disable=bare-except
                    pass

                if discord_connected.value:
                    try:
                        discord_rpc.update(
                            details=song_name,
                            state=artist_name,
                            large_image=f"{config.MAESTRO_SITE}/api/get_artwork?mount={stream_username}",
                            large_text=album_name,
                            buttons=(
                                [
                                    {
                                        "label": "Listen Along",
                                        "url": f"{config.MAESTRO_SITE}/listen/{stream_username}",
                                    }
                                ]
                                if stream_username
                                else []
                            ),
                        )
                        song_name = ""
                        artist_name = ""
                        album_name = ""
                        sleep(15)
                    except:  # pylint: disable=bare-except
                        discord_connected.value = 0
        else:
            if not discord_connected.value:
                try:
                    discord_rpc = pypresence.Presence(
                        client_id=config.DISCORD_ID
                    )
                    discord_rpc.connect()
                    discord_connected.value = 1
                except:  # pylint: disable=bare-except
                    pass


def _play(
    stdscr,
    playlist,
    volume,
    loop,
    clip_mode,
    reshuffle,
    update_discord,
    visualize,
    stream,
):
    helpers.init_curses(stdscr)

    if loop:
        next_playlist = playlist[:]
        helpers.bounded_shuffle(next_playlist, reshuffle)
    else:
        next_playlist = None

    player = helpers.PlaybackHandler(
        stdscr,
        playlist,
        volume,
        clip_mode,
        visualize,
        stream,
    )
    if can_mac_now_playing:
        player.can_mac_now_playing = True
        player.mac_now_playing = mac_now_playing

        player.mac_now_playing.title_queue = Queue()
        player.mac_now_playing.artist_queue = Queue()
        player.mac_now_playing.q = Queue()
        player.mac_now_playing.cover = cover_img

        ns_application = NSApplication.sharedApplication()
        # logo_ns_image = NSImage.alloc().initByReferencingFile_(
        #     "./maestro_icon.png"
        # )
        # ns_application.setApplicationIconImage_(logo_ns_image)
        ns_application.setActivationPolicy_(
            NSApplicationActivationPolicyProhibited
        )

        # NOTE: keep ref to delegate object, setDelegate_ doesn't retain
        delegate = AppDelegate.alloc().init()
        NSApp().setDelegate_(delegate)

        app_helper_process = multiprocessing.Process(
            daemon=True,
            target=app_helper_loop,
        )
        app_helper_process.start()
    if update_discord:
        player.initialize_discord_attrs()

        discord_presence_process = multiprocessing.Process(
            daemon=True,
            target=discord_presence_loop,
            args=(
                player.discord_queues["title"],
                player.discord_queues["artist"],
                player.discord_queues["album"],
                player.discord_connected,
                stream[0] if stream else None,
            ),
        )
        discord_presence_process.start()

    prev_volume = volume
    while player.i in range(len(player.playlist)):
        player.playback = Playback()
        player.playback.load_file(player.song_path)

        clip_string = player.playlist[player.i][3]
        if clip_string:
            player.clip = tuple(
                map(float, player.playlist[player.i][3].split())
            )
        else:
            player.clip = 0, player.playback.duration

        player.paused = False
        player.duration = full_duration = player.playback.duration
        player.update_metadata()
        player.playback.play()

        if player.clip_mode:
            clip_start, clip_end = player.clip
            player.duration = clip_end - clip_start
            player.seek(clip_start)

        start_time = pause_start = time()
        player.playback.set_volume(player.volume)

        player.last_timestamp = player.playback.curr_pos
        next_song = 1  # -1 if going back, 0 if restarting, +1 if next song
        player.restarting = False
        while True:
            if not player.playback.active or (
                player.clip_mode and player.playback.curr_pos > player.clip[1]
            ):
                next_song = not player.looping_current_song
                break

            # fade in first 2 seconds of clip
            if (
                player.clip_mode
                and clip_start != 0  # if clip doesn't start at beginning
                and clip_end - clip_start > 5  # if clip is longer than 5 secs
                and player.playback.curr_pos < clip_start + 2
            ):
                player.playback.set_volume(
                    player.volume * (player.playback.curr_pos - clip_start) / 2
                )
            else:
                player.playback.set_volume(player.volume)

            if player.can_mac_now_playing:  # Mac Now Playing event loop
                try:
                    if player.update_now_playing:
                        player.mac_now_playing.update()
                        player.update_now_playing = False
                    NSRunLoop.currentRunLoop().runUntilDate_(
                        NSDate.dateWithTimeIntervalSinceNow_(0.05)
                    )
                except:  # pylint: disable=bare-except
                    player.can_mac_now_playing = False

            if (
                player.can_mac_now_playing
                and not player.mac_now_playing.q.empty()
            ):
                c = player.mac_now_playing.q.get()
                if c in "nN":
                    if player.i == len(player.playlist) - 1 and not loop:
                        pass
                    else:
                        next_song = 1
                        player.playback.stop()
                        break
                elif c in "bB":
                    if player.i == 0:
                        pass
                    else:
                        next_song = -1
                        player.playback.stop()
                        break
                elif c in "rR":
                    player.playback.stop()
                    next_song = 0
                    break
                elif c in "qQ":
                    player.ending = True
                    break
                elif c == " ":
                    player.paused = not player.paused

                    if player.paused:
                        player.playback.pause()
                        pause_start = time()
                    else:
                        player.playback.resume()
                        start_time += time() - pause_start

                    if player.can_mac_now_playing:
                        player.mac_now_playing.paused = player.paused
                        if player.paused:
                            player.mac_now_playing.pause()
                        else:
                            player.mac_now_playing.resume()
                        player.update_now_playing = True

                    player.update_screen()
            else:
                c = stdscr.getch()  # int
                next_c = stdscr.getch()
                while next_c != -1:
                    c, next_c = next_c, stdscr.getch()

                if c != -1:
                    try:
                        ch = chr(c)
                        if ch in "\b\x7f":
                            c = curses.KEY_DC
                        elif ch in "\r\n":
                            c = curses.KEY_ENTER
                    except (ValueError, OverflowError):
                        ch = None

                    if player.prompting is None:
                        if c == curses.KEY_LEFT:
                            player.seek(
                                player.playback.curr_pos - config.SCRUB_TIME
                            )
                            player.update_screen()
                        elif c == curses.KEY_RIGHT:
                            player.seek(
                                player.playback.curr_pos + config.SCRUB_TIME
                            )
                            player.update_screen()
                        elif c == curses.KEY_UP:
                            player.scroller.scroll_backward()
                            player.update_screen()
                        elif c == curses.KEY_DOWN:
                            player.scroller.scroll_forward()
                            player.update_screen()
                        elif c == curses.KEY_ENTER:
                            player.i = player.scroller.pos - 1
                            next_song = 1
                            player.playback.stop()
                            break
                        elif c == curses.KEY_DC:
                            selected_song = player.scroller.pos
                            deleted_song_id = int(
                                player.playlist[selected_song][0]
                            )
                            del player.playlist[selected_song]

                            if loop:
                                if reshuffle:
                                    for i in range(len(next_playlist)):
                                        if (
                                            int(next_playlist[i][0])
                                            == deleted_song_id
                                        ):
                                            del next_playlist[i]
                                            break
                                else:
                                    del next_playlist[selected_song]

                            player.scroller.num_lines -= 1
                            if (
                                selected_song == player.i
                            ):  # deleted current song
                                next_song = 1
                                # will be incremented to i
                                player.scroller.pos = player.i - 1
                                player.i -= 1
                                player.playback.stop()
                                break
                            # deleted song before current
                            if selected_song < player.i:
                                player.i -= 1
                            # deleted last song
                            if selected_song == player.scroller.num_lines:
                                player.scroller.pos -= 1
                        elif ch is not None:
                            if ch in "nN":
                                if (
                                    player.i == len(player.playlist) - 1
                                    and not loop
                                ):
                                    pass
                                else:
                                    next_song = 1
                                    player.playback.stop()
                                    break
                            elif ch in "bB":
                                if player.i == 0:
                                    pass
                                else:
                                    next_song = -1
                                    player.playback.stop()
                                    break
                            elif ch in "rR":
                                player.restarting = True
                                player.playback.stop()
                                next_song = 0
                                break
                            elif ch in "lL":
                                player.looping_current_song = (
                                    player.looping_current_song + 1
                                ) % len(config.LOOP_MODES)
                                player.update_screen()
                            elif ch in "cC":
                                player.clip_mode = not player.clip_mode
                                if player.clip_mode:
                                    (
                                        clip_start,
                                        clip_end,
                                    ) = player.clip
                                    player.duration = clip_end - clip_start
                                    if (
                                        player.playback.curr_pos < clip_start
                                        or player.playback.curr_pos > clip_end
                                    ):
                                        player.seek(clip_start)
                                else:
                                    player.duration = full_duration
                                player.update_screen()
                            elif ch in "pP":
                                player.scroller.pos = player.i
                                player.scroller.resize()
                                player.update_screen()
                            elif ch in "gG":
                                if loop:
                                    player.playback.stop()
                                    player.i = len(player.playlist) - 1
                                    next_song = 1
                                    break
                            elif ch in "eE":
                                player.ending = not player.ending
                                player.update_screen()
                            elif ch in "qQ":
                                player.ending = True
                                break
                            elif ch in "dD":
                                if player.update_discord:
                                    player.update_discord = False
                                    discord_presence_process.terminate()
                                else:
                                    player.initialize_discord_attrs()
                                    player.update_discord_metadata()

                                    # start new process
                                    discord_presence_process = (
                                        multiprocessing.Process(
                                            daemon=True,
                                            target=discord_presence_loop,
                                            args=(
                                                player.discord_queues["title"],
                                                player.discord_queues["artist"],
                                                player.discord_queues["album"],
                                                player.discord_connected,
                                                stream[0] if stream else None,
                                            ),
                                        )
                                    )
                                    discord_presence_process.start()
                            elif ch in "iI":
                                player.prompting = (
                                    "",
                                    0,
                                    config.PROMPT_MODES["insert"],
                                )
                                curses.curs_set(True)
                                screen_size = stdscr.getmaxyx()
                                player.scroller.resize(screen_size[0] - 3)
                                player.update_screen()
                            elif ch in "aA":
                                player.prompting = (
                                    "",
                                    0,
                                    config.PROMPT_MODES["add"],
                                )
                                curses.curs_set(True)
                                screen_size = stdscr.getmaxyx()
                                player.scroller.resize(screen_size[0] - 3)
                                player.update_screen()
                            elif ch in "tT":
                                player.prompting = (
                                    "",
                                    0,
                                    config.PROMPT_MODES["tag"],
                                )
                                curses.curs_set(True)
                                screen_size = stdscr.getmaxyx()
                                player.scroller.resize(screen_size[0] - 3)
                                player.update_screen()
                            elif ch in "mM":
                                if player.volume == 0:
                                    player.volume = prev_volume
                                else:
                                    player.volume = 0
                                player.playback.set_volume(player.volume)

                                player.update_screen()
                            elif ch in "vV":
                                player.visualize = not player.visualize
                                player.update_screen()
                            elif ch == " ":
                                player.paused = not player.paused

                                if player.paused:
                                    player.playback.pause()
                                    pause_start = time()
                                else:
                                    player.playback.resume()
                                    start_time += time() - pause_start

                                if player.can_mac_now_playing:
                                    player.mac_now_playing.paused = (
                                        player.paused
                                    )
                                    if player.paused:
                                        player.mac_now_playing.pause()
                                    else:
                                        player.mac_now_playing.resume()
                                    player.update_now_playing = True

                                player.update_screen()
                            elif ch == "[":
                                player.volume = max(
                                    0, player.volume - config.VOLUME_STEP
                                )
                                player.playback.set_volume(player.volume)

                                player.update_screen()

                                prev_volume = player.volume
                            elif ch == "]":
                                player.volume = min(
                                    1, player.volume + config.VOLUME_STEP
                                )
                                player.playback.set_volume(player.volume)

                                player.update_screen()

                                prev_volume = player.volume
                    else:
                        if c == curses.KEY_LEFT:
                            # pylint: disable=unsubscriptable-object
                            player.prompting = (
                                player.prompting[0],
                                max(player.prompting[1] - 1, 0),
                                player.prompting[2],
                            )
                            player.update_screen()
                        elif c == curses.KEY_RIGHT:
                            # pylint: disable=unsubscriptable-object
                            player.prompting = (
                                player.prompting[0],
                                min(
                                    player.prompting[1] + 1,
                                    len(player.prompting[0]),
                                ),
                                player.prompting[2],
                            )
                            player.update_screen()
                        elif c == curses.KEY_UP:
                            player.scroller.scroll_backward()
                            player.update_screen()
                        elif c == curses.KEY_DOWN:
                            player.scroller.scroll_forward()
                            player.update_screen()
                        elif c == curses.KEY_DC:
                            # pylint: disable=unsubscriptable-object
                            player.prompting_delete_char()
                            player.update_screen()
                        elif c == curses.KEY_ENTER:
                            # pylint: disable=unsubscriptable-object
                            # fmt: off
                            if player.prompting[0].isnumeric() and player.prompting[2] in (
                                config.PROMPT_MODES["add"],
                                config.PROMPT_MODES["insert"],
                            ):
                                with open(
                                    config.SONGS_INFO_PATH,
                                    "r",
                                    encoding="utf-8",
                                ) as songs_file:
                                    for line in songs_file:
                                        details = line.strip().split("|")
                                        song_id = int(details[0])
                                        if song_id == int(player.prompting[0]):
                                            song_data = music_tag.load_file(
                                                os.path.join(
                                                    config.SETTINGS["song_directory"],
                                                    details[1],
                                                )
                                            )
                                            details += [
                                                (song_data[x[0]].value or f"No {x[1]}")
                                                for x in (
                                                    ("artist", "Artist"),
                                                    ("album", "Album"),
                                                    ("albumartist", "Album Artist"),
                                                )
                                            ]
                                            if player.prompting[2] == config.PROMPT_MODES["insert"]:
                                                player.playlist.insert(
                                                    player.scroller.pos + 1,
                                                    details,
                                                )
                                                inserted_pos = player.scroller.pos + 1
                                                if player.i > player.scroller.pos:
                                                    player.i += 1
                                            else:
                                                player.playlist.append(details)
                                                inserted_pos = len(player.playlist) - 1

                                            if loop:
                                                if reshuffle >= 0:
                                                    next_playlist.insert(randint(max(0, inserted_pos-reshuffle), min(len(playlist)-1, inserted_pos+reshuffle)), details)
                                                elif reshuffle == -1:
                                                    next_playlist.insert(randint(0, len(playlist) - 1), details)
                                                # else:
                                                #     if player_output.prompting[2] == config.PROMPT_MODES["insert"]:
                                                #         next_playlist.insert(
                                                #             player_output.scroller.pos + 1,
                                                #             details,
                                                #         )
                                                #     else:
                                                #         next_playlist.append(details)

                                            player.scroller.num_lines += 1

                                            player.prompting = None
                                            curses.curs_set(False)
                                            player.scroller.resize(screen_size[0] - 2)

                                            player.update_screen()
                                            break
                            elif (
                                "|" not in player.prompting[0]
                                and player.prompting[2]
                                == config.PROMPT_MODES["tag"]
                            ):
                                tags = player.prompting[0].split(",")

                                tagging_ids = {}
                                for i in range(len(player.playlist)):
                                    tagging_ids[int(player.playlist[i][0])] = i

                                songs_file = open(
                                    config.SONGS_INFO_PATH,
                                    "r",
                                    encoding="utf-8",
                                )
                                lines = songs_file.read().splitlines()
                                for i in range(len(lines)):
                                    details = lines[i].strip().split("|")
                                    song_id = int(details[0])
                                    if song_id in tagging_ids:
                                        if details[2]:
                                            new_tags = details[2].split(",")
                                        else:
                                            new_tags = []
                                        new_tags += [
                                            tag for tag in tags
                                            if tag not in new_tags
                                        ]
                                        details[2] = ",".join(new_tags)
                                        lines[i] = "|".join(details)
                                        player.playlist[tagging_ids[song_id]][2] = details[2]
                                songs_file.close()

                                songs_file = open(
                                    config.SONGS_INFO_PATH,
                                    "w",
                                    encoding="utf-8",
                                )
                                songs_file.write("\n".join(lines))
                                songs_file.close()

                                player.prompting = None
                                curses.curs_set(False)
                                player.update_screen()
                        elif c == 27:  # ESC key
                            player.prompting = None
                            curses.curs_set(False)
                            player.scroller.resize(screen_size[0] - 2)
                            player.update_screen()
                        elif ch is not None:
                            player.prompting = (
                                # pylint: disable=unsubscriptable-object
                                player.prompting[0][: player.prompting[1]]
                                + ch
                                + player.prompting[0][player.prompting[1] :],
                                player.prompting[1] + 1,
                                player.prompting[2],
                            )
                            player.update_screen()

            if (
                player.can_mac_now_playing
            ):  # sync Mac Now Playing pos with playback pos
                if (
                    abs(player.mac_now_playing.pos - player.playback.curr_pos)
                    > 1
                ):
                    player.seek(player.mac_now_playing.pos)
                    player.update_screen()
                else:
                    player.mac_now_playing.pos = round(player.playback.curr_pos)

            progress_bar_width = stdscr.getmaxyx()[1] - 18
            frame_duration = min(
                (
                    1
                    if progress_bar_width < config.MIN_PROGRESS_BAR_WIDTH
                    else player.duration / (progress_bar_width * 8)
                ),
                1 / config.FPS if player.visualize else 1,
            )
            if (
                abs(player.playback.curr_pos - player.last_timestamp)
                > frame_duration
            ):
                player.last_timestamp = player.playback.curr_pos
                player.update_screen()

            sleep(0.01)  # NOTE: so CPU usage doesn't fly through the roof

        player.pos_changed = True

        # region stats
        if player.paused:
            time_listened = pause_start - start_time
        else:
            time_listened = time() - start_time

        with open(
            config.TOTAL_STATS_PATH, "r+", encoding="utf-8"
        ) as stats_file:
            lines = stats_file.readlines()
            for j in range(len(lines)):
                song_id, listened = lines[j].strip().split("|")
                if song_id == player.song_id:
                    listened = float(listened) + time_listened
                    lines[j] = f"{song_id}|{listened}\n"
                    break

            # write out
            stats_file.seek(0)
            stats_file.write("".join(lines))
            stats_file.truncate()

        with open(
            config.CUR_YEAR_STATS_PATH, "r+", encoding="utf-8"
        ) as stats_file:
            lines = stats_file.readlines()
            for j in range(len(lines)):
                song_id, listened = lines[j].strip().split("|")
                if song_id == player.song_id:
                    listened = float(listened) + time_listened
                    lines[j] = f"{song_id}|{listened}\n"
                    break

            # write out
            stats_file.seek(0)
            stats_file.write("".join(lines))
            stats_file.truncate()
        # endregion

        if player.ending and not player.restarting:
            player.quit()
            if player.update_discord:
                discord_presence_process.terminate()
            return

        if next_song == -1:
            if player.i == player.scroller.pos:
                player.scroller.scroll_backward()
            player.i -= 1
        elif next_song == 1:
            if player.i == len(player.playlist) - 1:
                if loop:
                    next_next_playlist = next_playlist[:]
                    if reshuffle:
                        helpers.bounded_shuffle(next_next_playlist, reshuffle)
                    player.playlist, next_playlist = (
                        next_playlist,
                        next_next_playlist,
                    )
                    player.i = -1
                    player.scroller.pos = 0
                else:
                    return
            else:
                if player.i == player.scroller.pos:
                    player.scroller.scroll_forward()
            player.i += 1
        elif next_song == 0:
            if player.looping_current_song == config.LOOP_MODES["one"]:
                player.looping_current_song = config.LOOP_MODES["none"]


# endregion


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli():
    """A command line interface for playing music."""

    if not os.path.exists(config.MAESTRO_DIR):
        os.makedirs(config.MAESTRO_DIR)

    # ensure config.SETTINGS has all settings
    if not os.path.exists(config.SETTINGS_FILE):
        config.SETTINGS = config.DEFAULT_SETTINGS
    else:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
            config.SETTINGS = json.load(f)

        for key in config.DEFAULT_SETTINGS:
            if key not in config.SETTINGS:
                config.SETTINGS[key] = config.DEFAULT_SETTINGS[key]

    if not os.path.exists(config.SETTINGS["song_directory"]):
        os.makedirs(config.SETTINGS["song_directory"])

    if not os.path.exists(config.SONGS_INFO_PATH):
        with open(config.SONGS_INFO_PATH, "x", encoding="utf-8") as _:
            pass

    if not os.path.exists(config.STATS_DIR):
        os.makedirs(config.STATS_DIR)
    if not os.path.exists(config.TOTAL_STATS_PATH):
        with (
            open(config.TOTAL_STATS_PATH, "w", encoding="utf-8") as f,
            open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as g,
        ):
            for line in g:
                f.write(f"{line.strip().split('|')[0]}|0\n")
    if not os.path.exists(config.CUR_YEAR_STATS_PATH):
        with (
            open(config.CUR_YEAR_STATS_PATH, "w", encoding="utf-8") as f,
            open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as g,
        ):
            for line in g:
                f.write(f"{line.strip().split('|')[0]}|0\n")

    t = time()
    if t - config.SETTINGS["last_version_sync"] > 24 * 60 * 60:  # 1 day
        config.SETTINGS["last_version_sync"] = t
        try:
            response = requests.get(
                "https://pypi.org/pypi/maestro-music/json", timeout=5
            )
            latest_version = response.json()["info"]["version"]
            if helpers.versiontuple(latest_version) > helpers.versiontuple(
                VERSION
            ):
                click.secho(
                    f"A new version of maestro is available. Run 'pip install --upgrade maestro-music' to update to version {latest_version}.",
                    fg="yellow",
                )
        except:  # pylint: disable=bare-except
            pass

    # ensure config.SETTINGS_FILE is up to date
    with open(config.SETTINGS_FILE, "w", encoding="utf-8") as g:
        json.dump(config.SETTINGS, g)


@cli.command()
@click.argument("path_", metavar="PATH_OR_URL")
@click.argument("tags", nargs=-1)
@click.option(
    "-M/-nM",
    "--move/--no-move",
    "move_",
    default=False,
    help="Move file from PATH to maestro's internal song database instead of copying.",
)
@click.option(
    "-n",
    "--name",
    type=str,
    help="What to name the song, if you don't want to use the title from Youtube/Spotify or filename. Do not include an extension (e.g. '.wav'). Ignored if adding multiple songs.",
)
@click.option(
    "-R, -nR",
    "--recursive/--no-recursive",
    "recurse",
    default=False,
    help="If PATH is a folder, add songs in subfolders.",
)
@click.option(
    "-Y/-nY",
    "--youtube/--no-youtube",
    default=False,
    help="Add a song from a YouTube or YouTube Music URL.",
)
@click.option(
    "-S/-nS",
    "--spotify/--no-spotify",
    default=False,
    help="Add a song from Spotify (track URL, album URL, playlist URL, artist URL, or search query).",
)
@click.option(
    "-f",
    "--format",
    "format_",
    type=click.Choice(["wav", "mp3", "flac", "vorbis"]),
    help="Specify the format of the song if downloading from YouTube, YouTube Music, or Spotify URL.",
    default="mp3",
    show_default=True,
)
@click.option(
    "-c",
    "--clip",
    nargs=2,
    type=float,
    help="Add a clip. Ignored if adding multiple songs.",
)
@click.option(
    "-P/-nP",
    "--playlist/--no-playlist",
    "playlist_",
    default=False,
    help="If song URL passed is from a YouTube playlist, download all the songs. If the URL points directly to a playlist, this flag is unncessary.",
)
@click.option(
    "-m",
    "--metadata",
    "metadata_pairs",
    default=None,
    help="Add metadata to the song. If adding multiple songs, the metadata is added to each song. The format is 'key1:value1|key2:value2|...'.",
)
def add(
    path_,
    tags,
    move_,
    name,
    recurse,
    youtube,
    spotify,
    format_,
    clip,
    playlist_,
    metadata_pairs,
):
    """
    Add a new song.

    Adds the audio file located at PATH. If PATH is a folder, adds all files
    in PATH (including files in subfolders if '-r' is passed). The name of each
    song will be the filename (unless '-n' is passed). Filenames and tags cannot
    contain the character '|', and tags cannot contain ','.

    If the '-Y' or '--youtube' flag is passed, PATH is treated as a YouTube or
    YouTube Music URL instead of a file path.

    If the '-S' or '--spotify' flag is passed, PATH is treated as a Spotify
    track URL, album URL, playlist URL, artist URL, or search query instead of
    a file path.

    The '-c/--clip' option can be used to add a clip for the song. It takes two
    arguments, but unlike 'maestro clip', you cannot pass only the start time
    and not the end. To get around this, you can pass -1 as the end time, e.g.
    'maestro add -c 30 -1 https://www.youtube.com/watch?v=3VxuMErCd-E -y'. If
    adding multiple songs, this option cannot be used.

    The '-m/--metadata' option can be used to add metadata to the song. It takes
    a string of the format 'key1:value1|key2:value2|...'. If adding multiple
    songs, the metadata is added to each song.

    Possible editable metadata keys are: album, albumartist, artist, artwork,
    comment, compilation, composer, discnumber, genre, lyrics, totaldiscs,
    totaltracks, tracknumber, tracktitle, year, isrc

    Keys are not case sensitive and can contain arbitrary whitespace, '-', and
    '_' characters. In other words, 'Album Artist', 'album-artist', and
    'album_artist' are all synonyms for 'albumartist'. Also, 'disk' is
    synonymous with 'disc'.
    """

    paths = None
    if not (youtube or spotify) and not os.path.exists(path_):
        click.secho(
            f"The path '{path_}' does not exist. To download from a YouTube or YouTube Music URl, pass the '-Y/--youtube' flag. To download from a Spotify URl, pass the '-S/--spotify' flag.",
            fg="red",
        )
        return

    if youtube or spotify:
        if youtube and spotify:
            click.secho(
                "Cannot pass both '-y/--youtube' and '-s/--spotify' flags.",
                fg="red",
            )
            return

        if youtube:
            with YoutubeDL(
                {
                    "noplaylist": not playlist_,
                    "postprocessors": [
                        {
                            "key": "FFmpegMetadata",
                            "add_metadata": True,
                        },
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": format_,
                        },
                    ],
                    "outtmpl": {
                        "default": os.path.join(
                            config.MAESTRO_DIR, "%(title)s.%(ext)s"
                        )
                    },
                }
            ) as ydl:
                info = ydl.extract_info(path_, download=True)
                if "entries" in info:
                    for e in info["entries"]:
                        helpers.embed_artwork(e)
                else:
                    helpers.embed_artwork(info)
        else:
            if format_ == "vorbis":  # for spotdl only
                format_ = "ogg"

            cwd = os.getcwd()
            os.chdir(config.MAESTRO_DIR)
            try:
                subprocess.run(
                    [
                        "spotdl",
                        "download",
                        path_,
                        "--output",
                        "{title}.{output-ext}",
                        "--format",
                        format_,
                        "--headless",
                    ],
                    check=True,
                )
            except Exception as err:
                os.chdir(cwd)
                raise err

        paths = []
        for fname in os.listdir(config.MAESTRO_DIR):
            for f in config.EXTS:
                if fname.endswith(f):
                    raw_path = os.path.join(config.MAESTRO_DIR, fname)
                    sanitized_path = raw_path.replace("|", "-")

                    os.rename(raw_path, sanitized_path)

                    paths.append(sanitized_path)
            if fname.endswith(".part"):  # delete incomplete downloads
                os.remove(os.path.join(config.MAESTRO_DIR, fname))

        move_ = True

    if paths is None:
        if os.path.isdir(path_):
            paths = []
            if recurse:
                for dirpath, _, fnames in os.walk(path_):
                    for fname in fnames:
                        if os.path.splitext(fname)[1].lower() in config.EXTS:
                            paths.append(os.path.join(dirpath, fname))
            else:
                for fname in os.listdir(path_):
                    if os.path.splitext(fname)[1].lower() in config.EXTS:
                        full_path = os.path.join(path_, fname)
                        if os.path.isfile(full_path):
                            paths.append(full_path)
            if len(paths) == 0:
                click.secho(
                    f"No songs found in '{path_}'.",
                    fg="red",
                )
                return
        else:
            paths = [path_]

    if len(paths) > 1:
        if clip is not None:
            click.secho(
                "Cannot pass '-c/--clip' option when adding multiple songs.",
                fg="red",
            )
            return

        if name is not None:
            click.secho(
                "Cannot pass '-n/--name' option when adding multiple songs.",
                fg="red",
            )
            return

    if len(paths) == 1 and name is not None:
        new_path = os.path.join(
            config.MAESTRO_DIR, name + os.path.splitext(paths[0])[1]
        )
        # move/copy to config.MAESTRO_DIR (avoid name conflicts)
        if move_:
            move(paths[0], new_path)
        else:
            copy(paths[0], new_path)
        paths = [new_path]
        move_ = True  # always move (from temp loc in config.MAESTRO_DIR) if renaming

    if clip is not None and len(paths) == 1:
        song_duration = music_tag.load_file(paths[0])["#length"].value

        start, end = clip
        if start < 0:
            click.secho("Clip start time cannot be negative.", fg="red")
            return
        if start > song_duration:
            click.secho(
                "Clip start time cannot be greater than the song duration.",
                fg="red",
            )
            return

        if end == -1:
            end = song_duration
        elif end < start:
            click.secho(
                "Clip end time cannot be less than the clip start time.",
                fg="red",
            )
            return
        elif end > song_duration:
            click.secho(
                "Clip end time cannot be greater than the song duration.",
                fg="red",
            )
            return
    else:
        start = end = None

    # print(paths)
    if metadata_pairs is not None:
        # convert from "key:value,key:value" to [("key", "value")]
        metadata_pairs = [
            tuple(pair.strip().split(":")) for pair in metadata_pairs.split("|")
        ]
        keys_to_ignore = set()
        for key, value in metadata_pairs:
            if key not in config.METADATA_KEYS or key.startswith("#"):
                click.secho(
                    f"'{key}' is not a valid editable metadata key.", fg="red"
                )
                keys_to_ignore.add(key)
                continue
        metadata_pairs = list(
            filter(lambda t: t[0] not in keys_to_ignore, metadata_pairs)
        )

        for path in paths:
            song_data = music_tag.load_file(path)
            for key, value in metadata_pairs:
                song_data[key] = value
            song_data.save()

    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if not os.path.isdir(path) and ext not in config.EXTS:
            click.secho(f"'{ext}' is not supported.", fg="red")
            return

        for tag in tags:
            if "," in tag or "|" in tag:
                click.secho("Tags cannot contain ',' or '|'.", fg="red")
                return

        with open(config.SONGS_INFO_PATH, "a+", encoding="utf-8") as songs_file:
            songs_file.seek(0)  # start reading from beginning

            lines = songs_file.readlines()

            song_id = 1
            for line in lines:
                song_id = max(song_id, int(line.split("|")[0]) + 1)

            prepend_newline = lines and lines[-1][-1] != "\n"

            helpers.add_song(
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
@click.option(
    "-F/-nF",
    "--force/--no-force",
    default=False,
    help="Skip confirmation prompt.",
)
@click.option(
    "-T/-nT",
    "--tag/--no-tag",
    default=False,
    help="If passed, treat all arguments as tags, deleting every ocurrence of each tag.",
)
def remove(args, force, tag):
    """Remove either tag(s) or song(s) passed as ID(s)."""
    if not tag:
        try:
            song_ids = {int(song_id) for song_id in args}
            remaining_song_ids = {n for n in song_ids}
        except ValueError:
            click.secho(
                "Song IDs must be integers. To delete tags, pass the '-T/--tag' flag.",
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

        with open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
            lines = songs_file.read().splitlines()

            to_be_deleted = []
            skipping = set()
            for i in range(len(lines)):
                details = lines[i].strip().split("|")
                song_id = int(details[0])
                if song_id in remaining_song_ids:
                    remaining_song_ids.remove(song_id)

                    song_name = details[1]
                    song_path = os.path.join(
                        config.SETTINGS["song_directory"], song_name
                    )
                    if os.path.exists(song_path):
                        os.remove(song_path)
                    elif not force:
                        click.secho(
                            f"Warning: Song file '{song_name}' (ID {song_id}) not found. Would you still like to delete the song from the database? [y/n] ",
                            fg="yellow",
                            nl=False,
                        )
                        if input().lower() != "y":
                            click.echo(
                                f"Skipping song '{song_name}' (ID {song_id})."
                            )
                            skipping.add(song_id)
                            continue

                    to_be_deleted.append(i)

                    click.secho(
                        f"Removed song '{song_name}' with ID {song_id}.",
                        fg="green",
                    )

        for i in reversed(to_be_deleted):
            del lines[i]

        with open(config.SONGS_INFO_PATH, "w", encoding="utf-8") as songs_file:
            songs_file.write("\n".join(lines))

        for stats_file in os.listdir(config.STATS_DIR):  # delete stats
            if not stats_file.endswith(".txt"):
                continue

            stats_path = os.path.join(config.STATS_DIR, stats_file)
            with open(stats_path, "r", encoding="utf-8") as stats_file:
                stats_lines = stats_file.read().splitlines()

                to_be_deleted = []
                for i in range(len(stats_lines)):
                    details = stats_lines[i].strip().split("|")
                    song_id = int(details[0])
                    if song_id in song_ids and song_id not in skipping:
                        to_be_deleted.append(i)

            for i in reversed(to_be_deleted):
                del stats_lines[i]

            with open(stats_path, "w", encoding="utf-8") as stats_file:
                stats_file.write("\n".join(stats_lines))

        if remaining_song_ids:
            click.secho(
                f"Could not find the following song IDs: {', '.join(map(str, remaining_song_ids))}.",
                fg="red",
            )
    else:
        tags_to_remove = set(args)
        if not force:
            char = input(
                f"Are you sure you want to delete {len(tags_to_remove)} tag(s)? [y/n] "
            )

            if char.lower() != "y":
                print("Did not delete.")
                return

        with open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
            lines = songs_file.read().splitlines()
            for i in range(len(lines)):
                details = lines[i].strip().split("|")
                tags = details[2].split(",")
                for j in range(len(tags)):
                    if tags[j] in tags_to_remove:
                        del tags[j]
                details[2] = ",".join(tags)
                lines[i] = "|".join(details)

        with open(config.SONGS_INFO_PATH, "w", encoding="utf-8") as songs_file:
            songs_file.write("\n".join(lines))

        click.secho(
            f"Deleted all occurrences of {len(tags_to_remove)} tag(s).",
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
    num_songs = len(song_ids)
    tags = set(tags)
    for tag in tags:
        if "," in tag or "|" in tag:
            click.secho("Tags cannot contain ',' or '|'.", fg="red")
            return
    if tags:
        songs_file = open(config.SONGS_INFO_PATH, "r", encoding="utf-8")
        lines = songs_file.read().splitlines()
        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            song_id = int(details[0])
            if song_id in song_ids:
                song_ids.remove(song_id)

                if details[2]:
                    new_tags = details[2].split(",")
                else:
                    new_tags = []
                new_tags += [tag for tag in tags if tag not in new_tags]
                details[2] = ",".join(new_tags)
                lines[i] = "|".join(details)
        songs_file.close()

        songs_file = open(config.SONGS_INFO_PATH, "w", encoding="utf-8")
        songs_file.write("\n".join(lines))
        songs_file.close()

        if song_ids:
            click.secho(
                f"Could not find song(s) with ID(s) {', '.join(map(str, song_ids))}.",
                fg="red",
            )
            if len(song_ids) == num_songs:
                return
        click.secho(
            f"Added {len(tags)} tag(s) to {num_songs - len(song_ids)} song(s).",
            fg="green",
        )
    else:
        click.secho("No tags passed.", fg="red")


@cli.command()
@click.argument("song_ids", type=click.INT, required=True, nargs=-1)
@click.option(
    "-t",
    "--tag",
    "tags",
    help="Tags to remove.",
    multiple=True,
)
@click.option("-A/-nA", "--all/--no-all", "all_", default=False)
def untag(song_ids, tags, all_):
    """Remove tags from a specific song (passed as ID). Tags that the song
    doesn't have will be ignored.

    Passing the '-A/--all' flag will remove all tags from the song, unless TAGS
    is passed (in which case the flag is ignored)."""
    song_ids = set(song_ids)
    num_songs = len(song_ids)
    tags = set(tags)
    if tags:
        songs_file = open(config.SONGS_INFO_PATH, "r", encoding="utf-8")
        lines = songs_file.read().splitlines()
        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            song_id = int(details[0])
            if song_id in song_ids:
                song_ids.remove(song_id)

                tags_to_keep = [
                    tag for tag in details[2].split(",") if tag not in tags
                ]
                lines[i] = "|".join(
                    details[:2] + [",".join(tags_to_keep)] + details[3:]
                )
        songs_file.close()

        songs_file = open(config.SONGS_INFO_PATH, "w", encoding="utf-8")
        songs_file.write("\n".join(lines))
        songs_file.close()

        if song_ids:
            click.secho(
                f"Could not find song(s) with ID(s) {', '.join(map(str, song_ids))}.",
                fg="red",
            )
            if len(song_ids) == num_songs:
                return
        click.secho(
            f"Removed any occurrences of {len(tags)} tag(s) from {num_songs - len(song_ids)} song(s).",
            fg="green",
        )
    else:
        if not all_:
            click.secho(
                "No tags passed—to remove all tags, pass the '-A/--all' flag.",
                fg="red",
            )
        else:
            songs_file = open(config.SONGS_INFO_PATH, "r", encoding="utf-8")
            lines = songs_file.read().splitlines()
            for i in range(len(lines)):
                line = lines[i]
                details = line.strip().split("|")
                if int(details[0]) in song_ids:
                    lines[i] = "|".join(details[:2] + [""] + details[3:])
            songs_file.close()

            songs_file = open(config.SONGS_INFO_PATH, "w", encoding="utf-8")
            songs_file.write("\n".join(lines))
            songs_file.close()

            click.secho(
                f"Removed {len(tags)} tag(s) from {len(song_ids)} song(s).",
                fg="green",
            )


@cli.command()
@click.argument("tags", nargs=-1)
@click.option(
    "-e",
    "--exclude-tags",
    "exclude_tags",
    help="Exclude songs with these tags.",
    multiple=True,
)
@click.option(
    "-s",
    "--shuffle",
    "shuffle_",
    type=click.IntRange(-1, None),
    default=0,
    help="How to shuffle the queue on the first run. -1: random shuffle, 0: no shuffle, any other integer N: random shuffle with the constraint that each song is no farther than N spots away from its starting position.",
)
@click.option(
    "-r",
    "--reshuffle",
    "reshuffle",
    type=click.IntRange(-1, None),
    default=0,
    help="How to shuffle the queue on every run after the first. -1: random reshuffle, 0: no reshuffle, any other integer N: random reshuffle with the constraint that each song is no farther than N spots away from its previous position.",
)
@click.option(
    "-R/-nR",
    "--reverse/--no-reverse",
    "reverse",
    default=False,
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
@click.option(
    "-L/-nL",
    "--loop/--no-loop",
    "loop",
    default=False,
    help="Loop the queue.",
)
@click.option(
    "-C/-nC",
    "--clips/--no-clips",
    "clips",
    default=False,
    help="Start in clip mode. Can be toggled with 'c'.",
)
@click.option(
    "-D/-nD",
    "--discord/--no-discord",
    "discord",
    default=False,
    help="Discord rich presence. Ignored if required dependencies are not installed. Will fail silently and retry every time the song changes if Discord connection fails (e.g. Discord not open).",
)
@click.option(
    "-M/-nM",
    "--match-all/--no-match-all",
    "match_all",
    default=False,
    help="Play songs that match all tags, not any.",
)
@click.option(
    "-V/-nV",
    "--visualize/--no-visualize",
    "visualize",
    default=False,
    help="Visualize the song being played. Ignored if required dependencies are not installed.",
)
@click.option("-S/-nS", "--stream/--no-stream", "stream", default=False)
def play(
    tags,
    exclude_tags,
    shuffle_,
    reshuffle,
    reverse,
    only,
    volume,
    loop,
    clips,
    discord,
    match_all,
    visualize,
    stream,
):
    """Play your songs. If tags are passed, any song matching any tag will be in
    your queue, unless the '-M/--match-all' flag is passed, in which case
    every tag must be matched.

    \b
    \x1b[1mSPACE\x1b[0m\tpause/play
    \x1b[1mb\x1b[0m\t\tgo [b]ack to previous song
    \x1b[1mr\x1b[0m\t\t[r]eplay song
    \x1b[1mn\x1b[0m\t\tskip to [n]ext song
    \x1b[1ml\x1b[0m\t\t[l]oop the current song once ('l' in status bar). press again to loop infinitely ('L' in status bar). press once again to turn off looping
    \x1b[1mc\x1b[0m\t\ttoggle [c]lip mode
    \x1b[1mv\x1b[0m\t\ttoggle [v]isualization
    \x1b[1mLEFT\x1b[0m\trewind 5s
    \x1b[1mRIGHT\x1b[0m\tfast forward 5s
    \x1b[1m[\x1b[0m\t\tdecrease volume
    \x1b[1m]\x1b[0m\t\tincrease volume
    \x1b[1mm\x1b[0m\t\t[m]ute/unmute
    \x1b[1me\x1b[0m\t\t[e]nd the song player after the current song finishes (indicator in status bar, 'e' to cancel)
    \x1b[1mq\x1b[0m\t\t[q]uit the song player immediately
    \x1b[1mUP/DOWN\x1b[0m\tto scroll through the queue (mouse scrolling should also work)
    \x1b[1mp\x1b[0m\t\tsna[p] back to the currently [p]laying song
    \x1b[1mg\x1b[0m\t\tgo to the next pa[g]e/loop of the queue (ignored if not repeating queue)
    \x1b[1mBACKSPACE/DELETE\x1b[0m\tdelete the selected (not necessarily currently playing!) song from the queue
    \x1b[1md\x1b[0m\t\ttoggle [D]iscord rich presence
    \x1b[1ma\x1b[0m\t\t[a]dd a song (by ID) to the end of the queue. Opens a prompt to enter the ID: ENTER to confirm, ESC to cancel.
    \x1b[1mi\x1b[0m\t\t[i]nsert a song (by ID) in the queue after the selected song. Opens a prompt like 'a'.
    \x1b[1mt\x1b[0m\t\tadd a [t]ag to all songs in the queue. Opens a prompt like 'a'.

    \b
    song color indicates mode:
        \x1b[1;34mblue\x1b[0m\t\tnormal
        \x1b[1;33myellow\x1b[0m\tlooping current song (once or repeatedly)

    \b
    progress bar color indicates status:
        \x1b[1;33myellow\x1b[0m\tnormal (or current song doesn't have a clip)
        \x1b[1;35mmagenta\x1b[0m\tplaying clip

    For the color vision deficient, both modes also have indicators in the status bar.
    """
    playlist = []
    songs_not_found = []
    exclude_tags = set(exclude_tags)

    if only:
        only = set(only)
        with open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
            for line in songs_file:
                details = line.strip().split("|")
                song_id = int(details[0])
                if not os.path.exists(
                    os.path.join(config.SETTINGS["song_directory"], details[1])
                ):
                    songs_not_found.append(details)
                elif song_id in only:
                    playlist.append(details)

        if not playlist:
            click.secho("No songs found with the given IDs.", fg="red")
            return
    else:
        if not tags:
            with open(
                config.SONGS_INFO_PATH, "r", encoding="utf-8"
            ) as songs_file:
                for line in songs_file:
                    details = line.strip().split("|")
                    if not os.path.exists(
                        os.path.join(
                            config.SETTINGS["song_directory"], details[1]
                        )
                    ):
                        songs_not_found.append(details)
                    else:
                        playlist.append(details)
        else:
            tags = set(tags)
            with open(
                config.SONGS_INFO_PATH, "r", encoding="utf-8"
            ) as songs_file:
                for line in songs_file:
                    details = line.strip().split("|")
                    song_tags = set(details[2].split(","))
                    if not os.path.exists(
                        os.path.join(
                            config.SETTINGS["song_directory"], details[1]
                        )
                    ):
                        songs_not_found.append(details)
                    else:
                        if not match_all:
                            if tags & song_tags:  # intersection
                                playlist.append(details)
                        else:
                            if tags <= song_tags:  # subset
                                playlist.append(details)

    for details in playlist:
        if exclude_tags & set(details[2].split(",")):
            details[0] = -1
            continue

        song_data = music_tag.load_file(
            os.path.join(config.SETTINGS["song_directory"], details[1])
        )
        details += [
            (song_data["artist"].value or "No Artist"),
            (song_data["album"].value or "No Album"),
            (song_data["albumartist"].value or "No Album Artist"),
        ]

    playlist = list(filter(lambda x: x[0] != -1, playlist))

    helpers.bounded_shuffle(playlist, shuffle_)
    if reverse:
        playlist.reverse()

    if not playlist:
        click.secho("No songs found matching tag criteria.", fg="red")
    else:
        volume /= 100
        if stream:
            username = helpers.get_username()
            password = helpers.get_password()
            if username is None or password is None:
                if username is None:
                    click.secho("Username not found.", fg="red")
                if password is None:
                    click.secho("Password not found.", fg="red")
                click.secho("Please log in using 'maestro login'.", fg="red")
                return

        curses.wrapper(
            _play,
            playlist,
            volume,
            loop,
            clips,
            reshuffle,
            discord and can_update_discord,
            visualize,
            (username, password) if stream else None,
        )

    if songs_not_found:
        click.secho("Song files not found:", fg="red")
        for details in songs_not_found:
            click.secho(f"\t{details[1]} (ID {details[0]})", fg="red")


@cli.command()
@click.option(
    "-T/-nT",
    "--tag/--no-tag",
    "renaming_tag",
    default=False,
    help="If passed, rename tag instead of song (treat the arguments as tags).",
)
@click.argument("original")
@click.argument("new_name")
def rename(original, new_name, renaming_tag):
    """
    Rename a song.

    Renames the song with the ID ORIGINAL to NEW_NAME. The extension of the
    song (e.g. '.wav', '.mp3') is preserved—do not include it in the name.

    If the '-T/--tag' flag is passed, treats ORIGINAL as a tag, renaming all
    ocurrences of it to NEW_NAME—doesn't check if the tag NEW_NAME already,
    exists, so be careful!
    """
    songs_file = open(config.SONGS_INFO_PATH, "r", encoding="utf-8")
    lines = songs_file.read().splitlines()
    if not renaming_tag:
        if not original.isnumeric():
            click.secho(
                "Song ID must be an integer. To rename a tag, pass the '-T/--tag' flag.",
                fg="red",
            )
            return

        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            if os.path.splitext(details[1])[0] == new_name:
                click.secho(
                    f"A song with the name '{new_name}' already exists. Please choose another name.",
                    fg="red",
                )
                return

        original = int(original)
        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            if int(details[0]) == original:
                old_path = details[1]
                details[1] = new_name + os.path.splitext(old_path)[1]

                full_song_path = os.path.join(
                    config.SETTINGS["song_directory"], old_path
                )
                if not os.path.exists(full_song_path):
                    click.secho(
                        f"Song file '{old_path}' (ID {original}) not found.",
                        fg="red",
                    )
                    return

                lines[i] = "|".join(details)
                songs_file.close()
                songs_file = open(config.SONGS_INFO_PATH, "w", encoding="utf-8")
                songs_file.write("\n".join(lines))

                os.rename(
                    os.path.join(config.SETTINGS["song_directory"], old_path),
                    os.path.join(config.SETTINGS["song_directory"], details[1]),
                )

                click.secho(
                    f"Renamed song '{old_path}' with ID {original} to '{details[1]}'.",
                    fg="green",
                )

                break
        else:
            click.secho(f"Song with ID {original} not found.", fg="red")
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
        songs_file = open(config.SONGS_INFO_PATH, "w", encoding="utf-8")
        songs_file.write("\n".join(lines))

        click.secho(
            f"Replaced all ocurrences of tag '{original}' to '{new_name}'.",
            fg="green",
        )


@cli.command()
@click.argument("phrase")
@click.option(
    "-T/-nT",
    "--tag/--no-tag",
    "searching_for_tags",
    default=False,
    help="Searches for matching tags instead of song names.",
)
def search(phrase, searching_for_tags):
    """Search for song names (or tags with '-T' flag) that contain PHRASE. All
    songs/tags starting with PHRASE will appear before songs/tags containing but
    not starting with PHRASE. This search is case-insensitive."""
    phrase = phrase.lower()
    with open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
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
                click.secho("No results found.", fg="red")
                return

            songs_file.seek(0)
            for line in songs_file:
                details = line.strip().split("|")
                if int(details[0]) in results[0]:
                    helpers.print_entry(details, phrase)

            songs_file.seek(0)
            for line in songs_file:
                details = line.strip().split("|")
                if int(details[0]) in results[1]:
                    helpers.print_entry(details, phrase)

            click.secho(
                f"Found {len(results[0]) + len(results[1])} song(s).",
                fg="green",
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
                click.secho("No results found.", fg="red")
                return

            for tag in results[0]:
                print(tag)

            for tag in results[1]:
                print(tag)

            click.secho(
                f"Found {len(results[0]) + len(results[1])} tag(s).", fg="green"
            )


@cli.command(name="list")
@click.argument("search_tags", metavar="TAGS", nargs=-1)
@click.option(
    "-e",
    "--exclude-tags",
    "exclude_tags",
    multiple=True,
    help="Exclude songs (or tags if '-T/--tags' is passed) matching these tags.",
)
@click.option(
    "-s",
    "--sort",
    "sort_",
    type=click.Choice(
        (
            "none",
            "id",
            "i",
            "name",
            "n",
            "secs-listened",
            "s",
            "duration",
            "d",
            "times-listened",
            "t",
        )
    ),
    help="Sort by song ID, song name, seconds listened, duration or times listened (seconds listened divided by song duration). Increasing order.",
    default="none",
    show_default=True,
)
@click.option(
    "-R/-nR",
    "--reverse/--no-reverse",
    "reverse_",
    default=False,
    help="Reverse the sorting order (decreasing instead of increasing).",
)
@click.option(
    "-T/-nT",
    "--tag/--no-tag",
    "listing_tags",
    default=False,
    help="List tags matching TAGS instead of songs.",
)
@click.option(
    "-y",
    "--year",
    "year",
    help="Show time listened for a specific year, instead of the total. Passing 'cur' will show the time listened for the current year.",
)
@click.option("-t", "--top", "top", type=int, help="Show the top n songs/tags.")
@click.option(
    "-M/-nM",
    "--match-all/--no-match-all",
    "match_all",
    default=False,
    help="Shows songs that match all tags instead of any tag. Ignored if '-t/--tag' is passed.",
)
def list_(
    search_tags,
    exclude_tags,
    listing_tags,
    year,
    sort_,
    top,
    reverse_,
    match_all,
):
    """List the entries for all songs.

    Output format: ID, name, duration, listen time, times listened, [clip-start, clip-end] if clip exists, comma-separated tags if any

    If the '-T' flag is passed, tags will be listed instead of songs.

    Output format: tag, duration, listen time, times listened

    If TAGS are passed, any tag/song matching any tag in TAGS will be listed,
    unless the '-M/--match-all' flag is passed, in which case every tag must
    be matched (ignored if listing tags).
    """
    if top is not None:
        if top < 1:
            click.secho(
                "The option '-t/--top' must be a positive number.", fg="red"
            )
            return

    if year is None:
        stats_path = config.TOTAL_STATS_PATH
    else:
        if year == "cur":
            year = config.CUR_YEAR
            stats_path = config.CUR_YEAR_STATS_PATH
        else:
            if not year.isdigit():
                click.secho("Year must be a number or 'cur'.", fg="red")
                return
            stats_path = os.path.join(config.STATS_DIR, f"{year}.txt")
            if not os.path.exists(stats_path):
                click.secho(f"No stats found for year {year}.", fg="red")
                return

    if search_tags:
        search_tags = set(search_tags)

    if exclude_tags:
        exclude_tags = set(exclude_tags)

    num_lines = 0
    songs_not_found = []

    if listing_tags:
        if sort_ in ("id", "i"):
            click.secho(
                "Warning: cannot sort tags by ID. Defaulting to no sorting order.",
                fg="yellow",
            )
            sort_ = "none"

        with (
            open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file,
            open(stats_path, "r", encoding="utf-8") as stats_file,
        ):
            songs_lines = songs_file.readlines()
            stats = dict(
                map(
                    lambda t: (int(t[0]),) + t[1:],
                    map(
                        lambda x: tuple(map(float, x.strip().split("|"))),
                        stats_file.readlines(),
                    ),
                )
            )

            tags = defaultdict(lambda: (0.0, 0.0))
            for i in range(len(songs_lines)):
                song_id, song_name, tag_string = (
                    songs_lines[i].strip().split("|")[0:3]
                )
                if not os.path.exists(
                    os.path.join(config.SETTINGS["song_directory"], song_name)
                ):
                    songs_not_found.append((song_id, song_name))
                    continue
                song_id = int(song_id)
                if tag_string:
                    for tag in tag_string.split(","):
                        if (not search_tags or tag in search_tags) and (
                            not exclude_tags or tag not in exclude_tags
                        ):
                            tags[tag] = (
                                tags[tag][0] + stats[song_id],
                                tags[tag][1]
                                + music_tag.load_file(
                                    os.path.join(
                                        config.SETTINGS["song_directory"],
                                        song_name,
                                    )
                                )["#length"].value,
                            )

            tag_items = list(tags.items())

            if sort_ != "none":
                if sort_ in ("name", "n"):
                    sort_key = lambda t: t[0].lower()
                elif sort_ in ("secs-listened", "s"):
                    sort_key = lambda t: t[1][0]
                elif sort_ in ("duration", "d"):
                    sort_key = lambda t: t[1][1]
                elif sort_ in ("times-listened", "t"):
                    sort_key = lambda t: t[1][0] / t[1][1]
                tag_items.sort(key=sort_key)

            if reverse_:
                tag_items.reverse()

            for tag, (listen_time, total_duration) in tag_items:
                click.echo(
                    f"{tag} {click.style(helpers.format_seconds(total_duration, show_decimal=True), fg='bright_black')} {click.style(helpers.format_seconds(listen_time, show_decimal=True), fg='yellow')} {click.style('%.2f'%(listen_time/total_duration), fg='green')}"
                )
                num_lines += 1
                if top is not None and num_lines == top:
                    break
            if songs_not_found:
                click.secho("Song files not found:", fg="red")
                for song_id, song_name in songs_not_found:
                    click.secho(f"\t{song_name} (ID {song_id})", fg="red")
        return

    no_results = True
    with (
        open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file,
        open(stats_path, "r", encoding="utf-8") as stats_file,
    ):

        def check_if_file_exists(detail_string):
            details = detail_string.strip().split("|")
            if not os.path.exists(
                os.path.join(config.SETTINGS["song_directory"], details[1])
            ):
                songs_not_found.append(details)
                return False
            return True

        lines = list(filter(check_if_file_exists, songs_file.readlines()))

        stats = dict(
            map(
                lambda t: (int(t[0]),) + t[1:],
                map(
                    lambda x: tuple(map(float, x.strip().split("|"))),
                    stats_file.readlines(),
                ),
            )
        )

        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            song_id = int(details[0])

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
            if exclude_tags:
                if exclude_tags & tags:
                    lines[i] = ""
                    continue

            time_listened = stats[song_id]
            lines[i] = tuple(details) + (
                time_listened,
                music_tag.load_file(
                    os.path.join(config.SETTINGS["song_directory"], details[1])
                )["#length"].value,
            )

        lines = [line for line in lines if line]

        if sort_ != "none":
            if sort_ in ("id", "i"):
                sort_key = lambda t: int(t[0])
            if sort_ in ("name", "n"):
                sort_key = lambda t: t[1].lower()
            elif sort_ in ("secs-listened", "s"):
                sort_key = lambda t: float(t[-2])
            elif sort_ in ("duration", "d"):
                sort_key = lambda t: float(t[-1])
            elif sort_ in ("times-listened", "t"):
                sort_key = lambda t: float(t[-2]) / float(t[-1])
            lines.sort(key=sort_key)

        if reverse_:
            lines.reverse()

        for details in lines:
            helpers.print_entry(details)
            num_lines += 1
            no_results = False
            if top is not None and num_lines == top:
                break

    if songs_not_found:
        click.secho("Song files not found:", fg="red")
        for details in songs_not_found:
            click.secho(f"\t{details[1]} (ID {details[0]})", fg="red")
    elif no_results and search_tags:
        click.secho("No songs found matching tags.", fg="red")
    elif no_results:
        click.secho(
            "No songs found. Use 'maestro add' to add a song.", fg="red"
        )


@cli.command()
@click.option(
    "-y",
    "--year",
    "year",
    help="Show time listened for a specific year, instead of the total. Passing 'cur' will show the time listened for the current year.",
)
@click.option(
    "-I/-nI",
    "--artist-info/--no-artist-info",
    "song_info",
    default=True,
    help="Show the artist, album, and album artist for each song.",
)
@click.argument("song_ids", type=click.INT, nargs=-1, required=True)
def entry(song_ids, year, song_info):
    """
    View the details for specific song(s).

    Prints the details of the song(s) with the ID(s) SONG_IDS.

    \b
    Output format:
        ID, name, duration, listen time, times listened, [clip-start, clip-end] if clip exists, comma-separated tags if any
        artist - album (album artist), unless -nI/--no-artist-info is passed
    """
    song_ids = set(song_ids)

    if year is None:
        stats_path = config.TOTAL_STATS_PATH
    else:
        if year == "cur":
            year = config.CUR_YEAR
            stats_path = config.CUR_YEAR_STATS_PATH
        else:
            if not year.isdigit():
                click.secho("Year must be a number.", fg="red")
                return
            stats_path = os.path.join(config.STATS_DIR, f"{year}.txt")

    try:
        with (
            open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file,
            open(stats_path, "r", encoding="utf-8") as stats_file,
        ):
            lines = songs_file.readlines()
            stats = dict(
                map(
                    lambda t: (int(t[0]),) + t[1:],  # convert key to int
                    map(
                        lambda x: tuple(map(float, x.strip().split("|"))),
                        stats_file.readlines(),
                    ),
                )
            )
            for i in range(len(lines)):
                details = lines[i].strip().split("|")
                song_id = int(details[0])
                if song_id in song_ids:
                    if not os.path.exists(
                        os.path.join(
                            config.SETTINGS["song_directory"], details[1]
                        )
                    ):
                        click.secho(
                            f"Song file with ID {song_id} not found.", fg="red"
                        )
                        song_ids.remove(song_id)
                        continue
                    helpers.print_entry(
                        details
                        + [
                            stats[song_id],
                            music_tag.load_file(
                                os.path.join(
                                    config.SETTINGS["song_directory"],
                                    details[1],
                                )
                            )["#length"].value,
                        ],
                        show_song_info=song_info,
                    )
                    song_ids.remove(song_id)
    except FileNotFoundError:
        click.secho(f"No stats found for year {year}.", fg="red")

    if song_ids:
        song_ids = [str(id_) for id_ in song_ids]
        click.secho(
            f"No songs found with IDs: {', '.join(song_ids)}.", fg="red"
        )


@cli.command()
@click.argument("song", required=True)
@click.option(
    "-N/-nN",
    "--name/--no-name",
    "title",
    default=False,
    help="Treat SONG as a song name instead of an ID.",
)
def recommend(song, title):
    """
    Get recommendations from YT Music based on song titles. Note: this feature
    is experimental.

    Recommends songs (possibly explicit) using the YouTube Music API similar
    to the song with ID SONG to listen to.

    If the '-N' flag is passed, SONG is treated as a song name to search for
    on YouTube Music."""
    try:
        from ytmusicapi import YTMusic
    except ImportError:
        click.secho(
            "The 'recommend' command requires the 'ytmusicapi' package to be installed. Run 'pip install ytmusicapi' to install it.",
            fg="red",
        )
        return

    ytmusic = YTMusic()

    if title:
        results = ytmusic.search(song, filter="songs")
    else:
        if not song.isdigit():
            click.secho(
                "Song ID must be a number. To get recommendations by name, pass the '-N/--name' flag.",
                fg="red",
            )
            return

        with open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
            for line in songs_file:
                details = line.strip().split("|")
                if details[0] == song:
                    results = ytmusic.search(
                        os.path.splitext(details[1])[0], filter="songs"
                    )
                    break
            else:
                click.secho(f"No song found with ID {song}.", fg="red")
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
            f"https://music.youtube.com/watch?v={track['videoId']}",
            fg="bright_black",
        )


@cli.command()
@click.argument("song_ids", required=True, type=int, nargs=-1)
@click.option("-B/-nB", "--bottom/--no-bottom", "bottom", default=False)
def push(song_ids, bottom):
    """
    Move songs around to the bottom or top of the database.

    Push the song(s) with ID(s) SONG_IDS to the top of the database (as if they
    were the songs most recently added) in the order they are passed (e.g.
    'maestro push 1 2 3' will make the most recent song be 3).

    If the '-B' flag is passed, the song(s) will be pushed to the bottom of the
    list instead.
    """
    with open(config.SONGS_INFO_PATH, "r+", encoding="utf-8") as songs_file:
        lines = songs_file.readlines()

        lines_to_move = []
        for i in range(len(lines)):
            if int(lines[i].split("|")[0]) in song_ids:
                lines_to_move.append((i, lines[i]))

        for i, _ in reversed(lines_to_move):
            lines.pop(i)

        song_ids_with_order = dict(
            map(lambda x: (x[1], x[0]), enumerate(song_ids))
        )

        for i in range(len(lines_to_move)):
            lines_to_move[i] = (
                song_ids_with_order[int(lines_to_move[i][1].split("|")[0])],
                *lines_to_move[i],
            )

        lines_to_move.sort(key=lambda x: x[0], reverse=bottom)

        if not bottom:
            lines += [t[2] for t in lines_to_move]
        else:
            lines = [t[2] for t in lines_to_move] + lines

        songs_file.seek(0)
        songs_file.write("".join(lines))
        songs_file.truncate()


@cli.command(name="clip")
@click.argument("song_id", required=True, type=int)
@click.argument("start", required=False, type=float, default=None)
@click.argument("end", required=False, type=float, default=None)
@click.option(
    "-E/-nE",
    "--editor/--no-editor",
    "editor",
    default=True,
    help="Open the clip editor, even if START and END are passed. Ignored if neither START nor END are passed.",
)
def clip_(song_id, start, end, editor):
    """
    Create or edit the clip for a song.

    Sets the clip for the song with ID SONG_ID to the time range START to END
    (in seconds).

    If END is not passed, the clip will be from START to the end of the song.

    If neither START nor END are passed, a clip editor will be opened, in which
    you can move the start and end of the clip around using the arrow keys while
    listening to the song.

    If the '-E/--editor' flag is passed, the clip editor will be opened even if
    START and END are passed; this is useful if you want to fine-tune the clip.

    \b
    The editor starts out editing the start of the clip.
    \x1b[1mt\x1b[0m to toggle between editing the start and end of the clip.
    \x1b[1mSHIFT+LEFT/RIGHT\x1b[0m will move whichever clip end you are editing
        by 0.1 seconds, snap the current playback to that clip end (to exactly
        the clip start if editing start, end-1 if editing end), and pause.
    \x1b[1mLEFT/RIGHT\x1b[0m will move whichever clip end you are editing by 1
        second, snap the current playback to that clip end, and pause.
    \x1b[1mSPACE\x1b[0m will play/pause the song.
    \x1b[1mENTER\x1b[0m will exit the editor and save the clip.
    \x1b[1mq\x1b[0m will exit the editor without saving the clip.
    """
    if start is not None:
        if start < 0:
            click.secho("START must be a positive number.", fg="red")
            return
        if end is not None and end < 0:
            click.secho("END must be a positive number.", fg="red")
            return

    with open(config.SONGS_INFO_PATH, "r+", encoding="utf-8") as songs_file:
        lines = songs_file.readlines()

        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            if int(details[0]) == song_id:
                break
        else:
            click.secho(f"No song found with ID {song_id}.", fg="red")
            return

        song_name = details[1]
        if not os.path.exists(
            os.path.join(config.SETTINGS["song_directory"], song_name)
        ):
            click.secho(
                f"Song file {song_name} (ID {song_id}) not found.",
                fg="red",
            )
            return

        if start is None:  # clip editor
            start, end = curses.wrapper(helpers.clip_editor, details)
            if start is None:
                click.secho(f"No change in clip for {song_name}.", fg="green")
                return
            editor = False

        song_path = os.path.join(config.SETTINGS["song_directory"], song_name)
        duration = music_tag.load_file(song_path)["#length"].value

        if end is None:
            end = duration
        if start > duration:
            click.secho(
                "START must not be more than the song duration.", fg="red"
            )
            return
        if end > duration:
            click.secho(
                "END must not be more than the song duration.", fg="red"
            )
            return
        if start > end:
            click.secho("START must not be more than END.", fg="red")
            return

        if editor:
            start, end = curses.wrapper(
                helpers.clip_editor, details, start, end
            )
            if start is None:
                click.secho(f"No change in clip for {song_name}.", fg="green")
                return

        lines[i] = (
            "|".join(details[:3] + [str(start) + " " + str(end)] + details[5:])
            + "\n"
        )

        songs_file.seek(0)
        songs_file.write("".join(lines))
        songs_file.truncate()

        click.secho(f"Clipped {song_name} from {start} to {end}.", fg="green")


@cli.command()
@click.argument("song_ids", type=int, nargs=-1, required=False)
@click.option(
    "-A/-nA",
    "--all/--no-all",
    "all_",
    default=False,
    help="Remove clips for all songs. Ignores SONG_IDS.",
)
@click.option(
    "-F/-nF",
    "--force/--no-force",
    "force",
    default=False,
    help="Skip confirmation prompt.",
)
def unclip(song_ids, all_, force):
    """
    Remove clips for specific song(s).

    Removes clip for the song(s) with ID(s) SONG_IDS.

    If the '-A/--all' flag is passed, the clips for all songs will be removed,
    ignoring SONG_IDS. This prompts for confirmation unless the '-F/--force'
    flag is passed.
    """
    if not all_:
        if song_ids:
            song_ids = set(song_ids)
        else:
            click.secho(
                "No song IDs passed. To remove clips for all songs, pass the '-A/--all' flag.",
                fg="red",
            )
            return

    if all_ and not force:
        click.echo(
            "Are you sure you want to remove clips for all songs? This cannot be undone. [y/n] ",
        )
        if input().lower() != "y":
            return

    with open(config.SONGS_INFO_PATH, "r+", encoding="utf-8") as songs_file:
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


@cli.command()
@click.argument("song_ids", type=int, required=True, nargs=-1)
@click.option("-m", "--metadata", "pairs", type=str, required=False)
def metadata(song_ids, pairs):
    """
    View or edit the metadata for a song or songs.

    If the -m/--metadata option is not passed, prints the metadata for each song
    ID in SONG_IDS.

    If the option is passed, sets the metadata for the each song ID in SONG_IDS
    to the key-value pairs in -m/--metadata. The option should be passed as a
    string of the form 'key1:value1|key2:value2|...'.

    Possible editable metadata keys are: album, albumartist, artist, artwork,
    comment, compilation, composer, discnumber, genre, lyrics, totaldiscs,
    totaltracks, tracknumber, tracktitle, year, isrc

    Keys are not case sensitive and can contain arbitrary whitespace, '-', and
    '_' characters. In other words, 'Album Artist', 'album-artist', and
    'album_artist' are all synonyms for 'albumartist'. Also, 'disk' is
    synonymous with 'disc'.
    """

    if pairs:
        pairs = [tuple(pair.strip().split(":")) for pair in pairs.split("|")]

        valid_pairs = pairs[:]
        for key, value in pairs:
            if key not in config.METADATA_KEYS or key.startswith("#"):
                click.secho(
                    f"'{key}' is not a valid editable metadata key.",
                    fg="yellow",
                )
                valid_pairs.remove((key, value))
                continue

        if not valid_pairs:
            click.secho("No valid metadata keys passed.", fg="red")
            return

        click.secho(f"Valid pairs: {valid_pairs}", fg="green")

    with open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as songs_file:
        lines = songs_file.readlines()

        ids_not_found = set(song_ids)
        for i in range(len(lines)):
            details = lines[i].strip().split("|")
            song_id = int(details[0])
            if song_id in song_ids:
                ids_not_found.remove(song_id)
                song_name = details[1]
                song_path = os.path.join(
                    config.SETTINGS["song_directory"], song_name
                )
                if not os.path.exists(song_path):
                    click.secho(
                        f"Song file {song_name} (ID {song_id}) not found.",
                        fg="red",
                    )
                    continue

                song_data = music_tag.load_file(song_path)
                if pairs:
                    for key, value in valid_pairs:
                        song_data[key] = value
                    song_data.save()
                else:
                    click.echo("Metadata for ", nl=False)
                    click.secho(song_name, fg="blue", bold=True, nl=False)
                    click.echo(f" with ID {song_id}:")

                    for key in config.METADATA_KEYS:
                        try:
                            click.echo(
                                f"\t{key if not key.startswith('#') else key[1:]}: {song_data[key].value}"
                            )
                        except:  # pylint: disable=bare-except
                            pass

        if ids_not_found:
            click.secho(
                "Song IDs not found: "
                + ", ".join(sorted(map(str, ids_not_found))),
                fg="yellow",
            )


@cli.command(name="dir")
@click.argument("directory", type=click.Path(file_okay=False), required=False)
def dir_(directory):
    """
    Change the directory where maestro looks for songs. NOTE: This does not move
    any songs. It only changes where maestro looks for songs. You will have to
    move the songs yourself.

    If no argument is passed, prints the current directory.
    """

    if directory is None:
        click.echo(config.SETTINGS["song_directory"])
        return

    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(config.SETTINGS_FILE, "r+", encoding="utf-8") as settings_file:
        settings = json.load(settings_file)
        settings["song_directory"] = directory
        settings_file.seek(0)
        json.dump(settings, settings_file)
        settings_file.truncate()

    click.secho(f"Changed song directory to {directory}.", fg="green")


@cli.command(name="version")
def version():
    """
    Currently installed maestro version (PyPI version of the `maestro-music`
    package).
    """
    click.echo(f"maestro version: {VERSION}")


@cli.command(name="login")
@click.argument("username", required=False, default=None, type=str)
def login(username):
    """
    Log in to maestro. Currently the login system is only used for listen-along
    streaming, but may be used for other features in the future. The USERNAME
    argument is optional; if not passed, you will be prompted for your username.

    Will log out from existing username if a new one is passed.
    """
    helpers.login(username)


@cli.command(name="logout")
@click.option(
    "-f/-nF",
    "--force/--no-force",
    "force",
    default=False,
    help="Skip confirmation prompt.",
)
def logout(force):
    """
    Log out of maestro. Currently the login system is only used for listen-along
    streaming, but may be used for other features in the future.
    """
    if not force:
        click.echo("Are you sure you want to log out? [y/n] ", nl=False)
        if input().lower() != "y":
            return

    try:
        username = keyring.get_password("maestro-music", "username")
        keyring.delete_password("maestro-music", "username")
        click.secho(f"Logged out user '{username}'.", fg="green")
    except keyring.errors.PasswordDeleteError:
        click.secho("No user logged in.", fg="red")

    try:
        keyring.delete_password("maestro-music", "password")
        click.secho("Deleted password.", fg="green")
    except keyring.errors.PasswordDeleteError:
        click.secho("No password saved.", fg="red")


@cli.command(name="signup")
@click.argument("username", required=False, default=None, type=str)
@click.option("-l/-nL", "--login/--no-login", "login_", default=True)
def signup(username, login_):
    """
    Create a new maestro account. Currently the login system is only used for
    listen-along streaming, but may be used for other features in the future.

    The USERNAME argument is optional; if not passed, you will be prompted for
    a username.

    If the '-nL/--no-login' flag is passed, you will not be logged in after
    creating the account. You can still log in later using 'maestro login'.
    """
    helpers.signup(username, None, login_)
