# region imports
import curses
import multiprocessing
import os
import sys
import threading

import click
import msgspec

from collections import defaultdict
from queue import Queue
from random import randint
from shutil import move, copy, rmtree
from time import sleep, time

from maestro import config
from maestro import helpers
from maestro.__version__ import VERSION
from maestro.config import print_to_logfile  # pylint: disable=unused-import

# endregion

# region utility functions/classes


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
    username,
    password,
    lyrics,
    translated_lyrics,
):
    helpers.init_curses(stdscr)

    can_mac_now_playing = False
    if sys.platform == "darwin":
        try:
            from maestro.mac_presence import (
                MacNowPlaying,
                AppDelegate,
                app_helper_loop,
            )

            # pylint: disable=no-name-in-module,import-error
            from AppKit import (
                NSApp,
                NSApplication,
                # NSApplicationDelegate,
                NSApplicationActivationPolicyProhibited,
                NSDate,
                NSRunLoop,
            )

            # pylint: enable

            mac_now_playing = MacNowPlaying()
            can_mac_now_playing = True
        except (
            Exception  # pylint: disable=bare-except,broad-except
        ) as mac_import_err:
            print_to_logfile("macOS PyObjC import error:", mac_import_err)

    if loop:
        next_playlist = playlist[:]
        helpers.bounded_shuffle(next_playlist, reshuffle)
    else:
        next_playlist = None

    player = helpers.PlaybackHandler(
        stdscr,
        playlist,
        clip_mode,
        visualize,
        stream,
        (username, password) if username and password else (None, None),
        lyrics,
        translated_lyrics,
    )
    player.volume = volume
    if can_mac_now_playing:
        player.can_mac_now_playing = True
        player.mac_now_playing = mac_now_playing

        player.mac_now_playing.title_queue = Queue()
        player.mac_now_playing.artist_queue = Queue()
        player.mac_now_playing.q = Queue()

        ns_application = NSApplication.sharedApplication()
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
        player.threaded_initialize_discord()

    prev_volume = volume
    while player.i in range(len(player.playlist)):
        player.playback.load_file(player.song_path)

        if player.song.set_clip in player.song.clips:
            player.clip = player.song.clips[player.song.set_clip]
        else:
            player.clip = (0, player.playback.duration)
        player.paused = False

        player.lyrics = (
            player.song.parsed_override_lyrics or player.song.parsed_lyrics
        )
        player.lyric_pos = None
        if player.lyrics is not None:
            player.lyrics_scroller = helpers.Scroller(
                len(player.lyrics), player.screen_height - 1
            )
        player.translated_lyrics = player.song.parsed_translated_lyrics

        player.playback.play()
        player.set_volume(volume)
        player.update_metadata()

        # latter is clip-agnostic, former is clip-aware
        player.duration = player.playback.duration
        if player.clip_mode:
            clip_start, clip_end = player.clip
            player.duration = clip_end - clip_start
            player.seek(clip_start)

        start_time = pause_start = time()

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
                player.set_volume(
                    player.volume * (player.playback.curr_pos - clip_start) / 2
                )
            else:
                player.set_volume(player.volume)

            if player.can_mac_now_playing:  # macOS Now Playing event loop
                try:
                    if player.update_now_playing:
                        player.mac_now_playing.update()
                        player.update_now_playing = False
                    NSRunLoop.currentRunLoop().runUntilDate_(
                        NSDate.dateWithTimeIntervalSinceNow_(0.05)
                    )
                except Exception as e:
                    print_to_logfile("macOS Now Playing error:", e)
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

                    if c == curses.KEY_UP:
                        player.scroll_backward()
                        player.update_screen()
                    elif c == curses.KEY_DOWN:
                        player.scroll_forward()
                        player.update_screen()
                    elif c == curses.KEY_SLEFT:
                        if player.want_lyrics:
                            player.lyrics_width += 1
                            player.update_screen()
                    elif c == curses.KEY_SRIGHT:
                        if player.want_lyrics:
                            player.lyrics_width -= 1
                            player.update_screen()
                    elif c == 337:  # SHIFT + UP
                        player.playlist[player.scroller.pos - 1 : player.scroller.pos + 1] = (
                            player.playlist[player.scroller.pos: max(player.scroller.pos - 2, 0) or None: -1]
                        )
                        original_scroller_pos = player.scroller.pos
                        player.scroller.scroll_backward()
                        if original_scroller_pos == player.i:
                            player.i = player.scroller.pos
                        elif original_scroller_pos == player.i + 1:
                            player.i += 1
                    elif c == 336:  # SHIFT + DOWN
                        player.playlist[player.scroller.pos : player.scroller.pos + 2] = (
                            player.playlist[player.scroller.pos + 1 : max(player.scroller.pos - 1, 0) or None: -1]
                        )
                        original_scroller_pos = player.scroller.pos
                        player.scroller.scroll_forward()
                        if original_scroller_pos == player.i:
                            player.i = player.scroller.pos
                        elif original_scroller_pos == player.i - 1:
                            player.i -= 1
                    else:
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
                            elif c == curses.KEY_ENTER:
                                if player.focus == 0:
                                    # pylint: disable=invalid-unary-operand-type
                                    # -2 because pos can be 0
                                    next_song = -(player.scroller.pos) - 2
                                    player.playback.stop()
                                    break
                                elif player.focus == 1:
                                    if (
                                        helpers.is_timed_lyrics(player.lyrics)
                                        and player.lyric_pos is not None
                                    ):
                                        player.seek(
                                            player.lyrics[player.lyric_pos].time
                                        )
                                        player.snap_back()
                                        player.update_screen()
                            elif c == curses.KEY_DC:
                                if len(player.playlist) > 1:
                                    player.scroller.num_lines -= 1
                                    if (
                                        player.scroller.pos == player.i
                                    ):  # deleted current song
                                        next_song = 3
                                        player.playback.stop()
                                        break

                                    deleted_song = player.playlist[
                                        player.scroller.pos
                                    ]
                                    del player.playlist[player.scroller.pos]

                                    if loop:
                                        for i in range(len(next_playlist)):
                                            if next_playlist[i] == deleted_song:
                                                del next_playlist[i]
                                                break

                                    # deleted song before current
                                    if player.scroller.pos < player.i:
                                        player.i -= 1
                                    # deleted last song
                                    if (
                                        player.scroller.pos
                                        == player.scroller.num_lines
                                    ):
                                        player.scroller.pos -= 1

                                    player.scroller.refresh()
                            elif c == 27:  # ESC key
                                if player.show_help:
                                    player.show_help = False
                                    player.update_screen()
                            elif ch is not None:
                                if ch in "nN":
                                    if (
                                        not player.i == len(player.playlist) - 1
                                        or loop
                                    ):
                                        next_song = 1
                                        player.playback.stop()
                                        break
                                elif ch in "bB":
                                    if player.i != 0:
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
                                        clip_start, clip_end = player.clip
                                        player.duration = clip_end - clip_start
                                        if (
                                            player.playback.curr_pos
                                            < clip_start
                                            or player.playback.curr_pos
                                            > clip_end
                                        ):
                                            player.seek(clip_start)
                                    else:
                                        player.duration = (
                                            player.playback.duration
                                        )
                                    player.update_screen()
                                elif ch in "pP":
                                    player.snap_back()
                                    player.update_screen()
                                elif ch in "gG":
                                    if loop:
                                        player.playback.stop()
                                        next_song = 2
                                        break
                                elif ch in "eE":
                                    player.ending = not player.ending
                                    player.update_screen()
                                elif ch in "qQ":
                                    player.ending = True
                                    break
                                elif ch in "dD":
                                    if player.want_discord:
                                        player.want_discord = False
                                        if player.discord_rpc is not None:
                                            player.discord_rpc.close()
                                        player.discord_connected = 0
                                    else:

                                        def f():
                                            player.initialize_discord()
                                            player.update_discord_metadata()
                                            player.update_stream_metadata()

                                        threading.Thread(
                                            target=f,
                                            daemon=True,
                                        ).start()
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
                                        config.PROMPT_MODES["append"],
                                    )
                                    curses.curs_set(True)
                                    screen_size = stdscr.getmaxyx()
                                    player.scroller.resize(screen_size[0] - 3)
                                    player.update_screen()
                                elif ch == ",":
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

                                    player.update_screen()
                                elif ch in "vV":
                                    player.want_vis = not player.want_vis
                                    player.update_screen()
                                elif ch in "sS":
                                    player.want_stream = not player.want_stream
                                    if player.want_stream:
                                        if player.username is not None:
                                            threading.Thread(
                                                target=player.update_stream_metadata,
                                                daemon=True,
                                            ).start()
                                            player.ffmpeg_process.start()
                                    else:
                                        player.ffmpeg_process.terminate()
                                    player.update_discord_metadata()
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
                                    player.update_screen()
                                    prev_volume = player.volume
                                elif ch == "]":
                                    player.volume = min(
                                        100, player.volume + config.VOLUME_STEP
                                    )
                                    player.update_screen()
                                    prev_volume = player.volume
                                elif ch in "yY":
                                    player.want_lyrics = not player.want_lyrics
                                elif ch in "oO":
                                    helpers.SONG_DATA.load()
                                    helpers.SONGS.load()
                                    for song in player.playlist:
                                        song.reset()

                                    if (
                                        player.song.set_clip
                                        in player.song.clips
                                    ):
                                        player.clip = player.song.clips[
                                            player.song.set_clip
                                        ]
                                    else:
                                        player.clip = (
                                            0,
                                            player.playback.duration,
                                        )
                                    player.duration = (
                                        player.clip[1] - player.clip[0]
                                    )

                                    player.lyrics = (
                                        player.song.parsed_override_lyrics
                                        or player.song.parsed_lyrics
                                    )
                                    if player.lyrics is not None:
                                        player.lyrics_scroller = (
                                            helpers.Scroller(
                                                len(player.lyrics),
                                                player.screen_height - 1,
                                            )
                                        )
                                    player.translated_lyrics = (
                                        player.song.parsed_translated_lyrics
                                    )

                                    from keyring.errors import NoKeyringError

                                    try:
                                        player.username = helpers.get_username()
                                        player.password = helpers.get_password()
                                    except NoKeyringError:
                                        pass

                                    player.update_screen()
                                elif ch in "hH":
                                    player.show_help = not player.show_help
                                elif ch in "tT":
                                    player.want_translated_lyrics = (
                                        not player.want_translated_lyrics
                                        and player.want_lyrics
                                    )
                                elif ch in "fF":
                                    player.prompting = (
                                        "",
                                        0,
                                        config.PROMPT_MODES["find"],
                                    )
                                    curses.curs_set(True)
                                    screen_size = stdscr.getmaxyx()
                                    player.scroller.resize(screen_size[0] - 3)
                                    player.update_screen()
                                elif ch == "{":
                                    player.snap_back()
                                    player.focus = 0
                                elif ch == "}":
                                    player.snap_back()
                                    player.focus = 1
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
                            elif c == curses.KEY_DC:
                                # pylint: disable=unsubscriptable-object
                                player.prompting_delete_char()
                                player.update_screen()
                            elif c == curses.KEY_ENTER:
                                # pylint: disable=unsubscriptable-object
                                # fmt: off
                                if (
                                    player.prompting[2] == config.PROMPT_MODES["tag"]
                                ):
                                    tags = set(player.prompting[0].split(","))

                                    for song in player.playlist:
                                        song.tags |= tags

                                    player.prompting = None
                                    curses.curs_set(False)
                                    player.scroller.resize(screen_size[0] - 2)

                                    player.update_screen()
                                elif player.prompting[2] == config.PROMPT_MODES["find"]:
                                    try:
                                        song = helpers.CLICK_SONG(player.prompting[0])
                                        i = player.playlist.index(song)
                                        if i != -1:
                                            player.scroller.pos = i

                                        player.prompting = None
                                        curses.curs_set(False)
                                        player.scroller.resize(screen_size[0] - 2)

                                        player.update_screen()
                                    except click.BadParameter:
                                        pass
                                else:
                                    try:
                                        song = helpers.CLICK_SONG(player.prompting[0])
                                        if player.prompting[2] == config.PROMPT_MODES["insert"]:
                                            player.playlist.insert(
                                                player.scroller.pos + 1,
                                                song,
                                            )
                                            inserted_pos = player.scroller.pos + 1
                                            if player.i > player.scroller.pos:
                                                player.i += 1
                                        else:
                                            player.playlist.append(song)
                                            inserted_pos = len(player.playlist) - 1

                                        if loop:
                                            if reshuffle >= 0:
                                                next_playlist.insert(randint(max(0, inserted_pos-reshuffle), min(len(playlist)-1, inserted_pos+reshuffle)), song)
                                            elif reshuffle == -1:
                                                next_playlist.insert(randint(0, len(playlist) - 1), song)

                                        player.scroller.num_lines += 1

                                        player.prompting = None
                                        curses.curs_set(False)
                                        player.scroller.resize(screen_size[0] - 2)

                                        player.update_screen()
                                    except click.BadParameter:
                                        pass
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
                                    + player.prompting[0][
                                        player.prompting[1] :
                                    ],
                                    player.prompting[1] + 1,
                                    player.prompting[2],
                                )
                                player.update_screen()

            if (
                player.can_mac_now_playing
            ):  # sync macOS Now Playing pos with playback pos
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
                1 / config.FPS if player.want_vis else 1,
            )
            if (
                abs(player.playback.curr_pos - player.last_timestamp)
                > frame_duration
            ):
                player.last_timestamp = player.playback.curr_pos
                player.update_screen()

            sleep(0.01)  # NOTE: so CPU usage doesn't fly through the roof

        if player.paused:
            time_listened = pause_start - start_time
        else:
            time_listened = time() - start_time

        # region update stats
        def stats_update(s: helpers.Song, t: float):
            s.listen_times[config.CUR_YEAR] += t
            s.listen_times["total"] += t

        threading.Thread(
            target=stats_update, args=(player.song, time_listened), daemon=True
        ).start()
        # endregion

        if player.ending and not player.restarting:
            player.quit()
            if player.can_mac_now_playing:
                app_helper_process.terminate()
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
        elif next_song <= -2:  # user pos -> -(pos + 2)
            player.i = -next_song - 2
        elif next_song == 2:  # next page
            next_next_playlist = next_playlist[:]
            if reshuffle:
                helpers.bounded_shuffle(next_next_playlist, reshuffle)
            player.playlist, next_playlist = (
                next_playlist,
                next_next_playlist,
            )
            player.i = 0
            player.scroller.pos = 0
        elif next_song == 3:  # deleted current song
            deleted_song = player.playlist[player.i]
            del player.playlist[player.i]
            if loop:
                for i in range(len(next_playlist)):
                    if next_playlist[i] == deleted_song:
                        del next_playlist[i]
                        break


# endregion


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def cli(ctx: click.Context):
    """A command line interface for playing music."""

    # ~/.maestro-files
    if not os.path.exists(config.MAESTRO_DIR):
        os.makedirs(config.MAESTRO_DIR)

    # ensure config.SETTINGS has all settings
    update_settings = False
    if not os.path.exists(config.SETTINGS_FILE):
        config.settings = config.DEFAULT_SETTINGS
        update_settings = True
    else:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
            s = f.read()
            if s:
                config.settings = msgspec.json.decode(s)
                for key in config.DEFAULT_SETTINGS:
                    if key not in config.settings:
                        config.settings[key] = config.DEFAULT_SETTINGS[key]
                        update_settings = True
            else:
                config.settings = config.DEFAULT_SETTINGS
                update_settings = True

    # ~/.maestro-files/songs.json
    if not os.path.exists(config.SONGS_INFO_PATH):
        if os.path.exists(config.OLD_SONGS_INFO_PATH):
            if ctx.invoked_subcommand == "migrate":
                return
            ctx.fail(
                "Legacy song data detected. Please run 'maestro migrate' to convert the old songs file to the new format."
            )

        with open(config.SONGS_INFO_PATH, "x", encoding="utf-8") as _:
            pass

    # ~/.maestro-files/songs/
    if not os.path.exists(config.settings["song_directory"]):
        os.makedirs(config.settings["song_directory"])

    t = time()
    if t - config.settings["last_version_sync"] > 24 * 60 * 60:  # 1 day
        config.settings["last_version_sync"] = t
        update_settings = True
        try:
            import requests

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
        except Exception as e:
            print_to_logfile("Failed to check for updates:", e)

    # ensure config.SETTINGS_FILE is up to date
    if update_settings:
        import safer

        with safer.open(config.SETTINGS_FILE, "wb") as g:
            g.write(msgspec.json.encode(config.settings))

    # ensure config.LOGFILE is not too large (1 MB)
    t = time()
    if os.path.exists(config.LOGFILE) and os.path.getsize(config.LOGFILE) > 1e6:
        # move to backup
        backup_path = os.path.join(config.OLD_LOG_DIR, f"maestro-{int(t)}.log")
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        move(config.LOGFILE, backup_path)

    # delete old log files
    if os.path.exists(config.OLD_LOG_DIR):
        for file in os.listdir(config.OLD_LOG_DIR):
            if file.endswith(".log"):
                if t - int(file.split(".")[0].split("-")[1]) > 24 * 60 * 60:
                    os.remove(os.path.join(config.OLD_LOG_DIR, file))


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
    help="What to name the song, if you don't want to use the title from Youtube/Spotify/filename. Do not include an extension (e.g. '.wav'). Ignored if adding multiple songs.",
)
@click.option(
    "-R/-nR",
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
    type=click.Choice(("wav", "mp3", "flac", "vorbis")),
    help="Specify the format of the song if downloading from YouTube, YouTube Music, or Spotify URL.",
    default="mp3",
    show_default=True,
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
@click.option(
    "-a",
    "--artist",
    help="Specify the artist. If also specified in '-m/--metadata', this takes precedence.",
)
@click.option(
    "-b",
    "--album",
    help="Specify the album. If also specified in '-m/--metadata', this takes precedence.",
)
@click.option(
    "-c",
    "--album-artist",
    help="Specify the album artist. If also specified in '-m/--metadata', this takes precedence.",
)
@click.option(
    "-nD/-D",
    "--skip-dupes/--no-skip-dupes",
    default=False,
    help="Skip adding song names that are already in the database. If not passed, 'copy' is appended to any duplicate names.",
)
@click.option(
    "-L/-nL",
    "--lyrics/--no-lyrics",
    default=True,
    help="Search for and download lyrics for the song.",
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
    playlist_,
    metadata_pairs,
    artist,
    album,
    album_artist,
    skip_dupes,
    lyrics,
):
    """
    Add a new song.

    Adds the audio file located at PATH. If PATH is a folder, adds all files
    in PATH (including files in subfolders if '-R/--recursive' is passed). If
    '-M/--move' is passed, the file is moved from PATH to maestro's internal
    song database instead of copied.

    If the '-Y/--youtube' flag is passed, PATH is treated as a YouTube or
    YouTube Music URL instead of a file path.

    If the '-S/--spotify' flag is passed, PATH is treated as a Spotify
    track URL, album URL, playlist URL, artist URL, or search query instead of
    a file path.

    The default format for downloading from YouTube, YouTube Music, or Spotify
    is 'mp3'. The '-f/--format' option can be used to specify the format: 'wav',
    'mp3', 'flac', or 'vorbis' (.ogg container).

    If adding only one song, the '-n/--name' option can be used to specify the
    name of the song. Do not include an extension (e.g. '.wav').

    The '-m/--metadata' option can be used to add metadata to the song. It takes
    a string of the format 'key1:value1|key2:value2|...'. If adding multiple
    songs, the metadata is added to each song.

    Possible editable metadata keys are: album, albumartist, artist, artwork,
    comment, compilation, composer, discnumber, genre, lyrics, totaldiscs,
    totaltracks, tracknumber, tracktitle, year, isrc

    If the '-nD/--skip-dupes' flag is passed, song names that are already in
    the database are skipped. If not passed, 'copy' is appended to any duplicate
    names.
    """

    paths = None
    if not (youtube or spotify or os.path.exists(path_)):
        click.secho(
            f"The path '{path_}' does not exist. To download from a YouTube or YouTube Music URl, pass the '-Y/--youtube' flag. To download from a Spotify URl, pass the '-S/--spotify' flag.",
            fg="red",
        )
        return

    if youtube or spotify:
        if youtube and spotify:
            click.secho(
                "Cannot pass both '-Y/--youtube' and '-S/--spotify' flags.",
                fg="red",
            )
            return

        if youtube:
            from spotdl.utils.ffmpeg import get_ffmpeg_path
            from yt_dlp import YoutubeDL

            if get_ffmpeg_path() is None:
                click.secho(
                    "FFmpeg is not installed: you can install it globally or run 'maestro download-ffmpeg' to download it internally.",
                    fg="red",
                )
                return

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
                    "ffmpeg_location": str(get_ffmpeg_path()),
                }
            ) as ydl:
                info = ydl.extract_info(path_, download=True)
                if "entries" in info:
                    for e in info["entries"]:
                        helpers.yt_embed_artwork(e)
                else:
                    helpers.yt_embed_artwork(info)
        else:
            from spotdl import (
                console_entry_point as original_spotdl_entry_point,
            )
            from spotdl.utils.ffmpeg import FFmpegError

            if format_ == "vorbis":  # for spotdl only
                format_ = "ogg"

            cwd = os.getcwd()
            os.chdir(config.MAESTRO_DIR)

            def spotdl_entry_point(args):
                original_argv = sys.argv
                sys.argv = args
                try:
                    original_spotdl_entry_point()
                except Exception as e:
                    os.chdir(cwd)
                    raise e
                finally:
                    sys.argv = original_argv

            try:
                spotdl_entry_point(
                    [
                        "download",
                        path_,
                        "--output",
                        "{title}.{output-ext}",
                        "--format",
                        format_,
                        "--headless",
                    ],
                )
            except FFmpegError:
                click.secho(
                    "FFmpeg is not installed: you can install it globally or run 'maestro download-ffmpeg' to download it internally.",
                    fg="red",
                )
                return

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

    if paths is None:  # not downloading from YouTube or Spotify
        if os.path.isdir(path_):  # get all songs to be added
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

    if not paths:
        click.secho("No songs to add.", fg="red")
        return

    if name is not None:  # renaming
        if len(paths) > 1:
            click.secho(
                "Cannot pass '-n/--name' option when adding multiple songs.",
                fg="yellow",
            )

        ext = os.path.splitext(paths[0])[1].lower()
        if not os.path.isdir(paths[0]) and ext not in config.EXTS:
            click.secho(f"'{ext}' is not supported.", fg="red")
            return

        new_path = os.path.join(config.MAESTRO_DIR, name + ext)
        # move/copy to config.MAESTRO_DIR (avoid name conflicts)
        if move_:
            move(paths[0], new_path)
        else:
            copy(paths[0], new_path)
        paths = [new_path]
        move_ = True  # always move (from temp loc in config.MAESTRO_DIR) if renaming

    if metadata_pairs is not None:
        # convert from "key:value|key:value" to [("key", "value")]
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
            elif key == "artist" and artist is not None:
                keys_to_ignore.add(key)
            elif key == "album" and album is not None:
                keys_to_ignore.add(key)
            elif key == "albumartist" and album_artist is not None:
                keys_to_ignore.add(key)
        metadata_pairs = list(
            filter(lambda t: t[0] not in keys_to_ignore, metadata_pairs)
        )

    abc_opts = list(
        filter(
            lambda t: t[1] is not None,
            [
                ("artist", artist),
                ("album", album),
                ("albumartist", album_artist),
            ],
        )
    )
    if abc_opts:
        metadata_pairs = metadata_pairs or []
        metadata_pairs.extend(abc_opts)

    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if not os.path.isdir(path) and ext not in config.EXTS:
            click.secho(f"'{ext}' is not supported.", fg="red")
            continue

        song_fname = os.path.split(path)[1]
        song_title = os.path.splitext(song_fname)[0]
        dest_path = os.path.join(config.settings["song_directory"], song_fname)

        for song in helpers.SONGS:
            if song.song_title == song_title:
                if skip_dupes:
                    click.secho(
                        f"Song with name '{song_title}' already exists, skipping.",
                        fg="yellow",
                    )
                    os.remove(path)
                else:
                    click.secho(
                        f"Song with name '{song_title}' already exists, 'copy' will be appended to the song name.",
                        fg="yellow",
                    )
                    song_fname = song_title + " copy" + ext

                    dest_path = os.path.join(
                        config.settings["song_directory"], song_fname
                    )
                break

        if move_:
            move(path, dest_path)
        else:
            copy(path, dest_path)

        song = helpers.SONG_DATA.add_song(dest_path, tags)

        if metadata_pairs is not None:
            for path in paths:
                for key, value in metadata_pairs:
                    song.set_metadata(key, value)

        if lyrics:
            import syncedlyrics

            try:
                lyrics = syncedlyrics.search(
                    f"{song.artist} - {song_title}", allow_plain_format=True
                )
            except TypeError:
                try:
                    lyrics = syncedlyrics.search(song_title)
                except Exception as e:
                    click.secho(
                        f'Failed to download lyrics for "{song_title}": {e}',
                        fg="red",
                    )
            except Exception as e:
                click.secho(
                    f'Failed to download lyrics for "{song_title}": {e}',
                    fg="red",
                )
            else:
                if lyrics:
                    click.secho(
                        f'Downloaded lyrics for "{song_title}".', fg="green"
                    )
                    song.raw_lyrics = lyrics
                else:
                    click.secho(
                        f'No lyrics found for "{song_title}".', fg="yellow"
                    )

        if not tags:
            tags_string = ""
        elif len(tags) == 1:
            tags_string = f" and tag '{tags[0]}'"
        else:
            tags_string = f" and tags {', '.join([repr(tag) for tag in tags])}"

        click.secho(
            f"Added song '{song.song_file}' with ID {song.song_id}"
            + tags_string
            + f" and metadata (artist: {song.artist}, album: {song.album}, albumartist: {song.album_artist}).",
            fg="green",
        )


@cli.command()
@click.argument("args", required=True, nargs=-1)
@click.option(
    "-F/-nF",
    "--force/--no-force",
    default=False,
    help="Skip confirmation prompt(s).",
)
@click.option(
    "-T/-nT",
    "--tag/--no-tag",
    default=False,
    help="If passed, treat all arguments as tags, deleting every ocurrence of each tag.",
)
def remove(args, force, tag):
    """Remove tag(s) or song(s)."""
    if not tag:
        songs: set[helpers.Song] = {helpers.CLICK_SONG(v) for v in args}

        if not force:
            char = input(
                f"Are you sure you want to delete {helpers.pluralize(len(songs), 'song')}? [y/n] "
            )

            if char.lower() != "y":
                print("Did not delete.")
                return

        for song in songs:
            if os.path.exists(song.song_path):
                os.remove(song.song_path)
            elif not force:
                click.secho(
                    f"Warning: Song file '{song.song_path}' (ID {song.song_id}) not found. Would you still like to delete the song from the database? [y/n] ",
                    fg="yellow",
                    nl=False,
                )
                if input().lower() != "y":
                    click.echo(
                        f'Skipping song "{song.song_title}" (ID {song.song_id}).'
                    )
                    continue
            click.secho(
                f'Removed song "{song.song_title}" (ID {song.song_id}).',
                fg="green",
            )
            song.remove_from_data()
    else:
        tags_to_remove = set(args)
        if not force:
            char = input(
                f"Are you sure you want to delete {helpers.pluralize(len(tags_to_remove), 'tag')}? [y/n] "
            )

            if char.lower() != "y":
                print("Did not delete.")
                return

        for song in helpers.SONGS:
            song.tags -= tags_to_remove

        click.secho(
            f"Deleted all occurrences of {helpers.pluralize(len(tags_to_remove), 'tag')}.",
            fg="green",
        )


@cli.command(name="tag")
@click.argument("songs", type=helpers.CLICK_SONG, required=True, nargs=-1)
@click.option(
    "-t",
    "--tag",
    "tags",
    help="Tags to add.",
    multiple=True,
)
def tag_(songs, tags):
    """Add tags to songs."""
    if tags:
        tags = set(tags)
        for song in songs:
            song.tags |= tags
        click.secho(
            f"Added {helpers.pluralize(len(tags), 'tag')} to {helpers.pluralize(len(songs), 'song')}.",
            fg="green",
        )
    else:
        click.secho("No tags passed.", fg="red")


@cli.command()
@click.argument("songs", type=helpers.CLICK_SONG, required=True, nargs=-1)
@click.option(
    "-t",
    "--tag",
    "tags",
    help="Tags to remove.",
    multiple=True,
)
@click.option("-A/-nA", "--all/--no-all", "all_", default=False)
@click.option("-F/-nF", "--force/--no-force", default=False)
def untag(songs, tags, all_, force):
    """Remove tags from songs. Tags that a song doesn't have will be ignored.

    Passing the '-A/--all' flag will remove all tags from each song, unless TAGS
    is passed (in which case the flag is ignored). Prompts for confirmation
    unless the '-F/--force' flag is passed."""
    if tags:
        tags = set(tags)
        for song in songs:
            song.tags -= tags
        click.secho(
            f"Removed any occurrences of {helpers.pluralize(len(tags), 'tag')} from {helpers.pluralize(len(songs), 'song')}.",
            fg="green",
        )
    else:
        if not all_:
            click.secho(
                "No tags passed—to remove all tags, pass the '-A/--all' flag.",
                fg="red",
            )
        else:
            if (
                force
                or input(
                    f"Are you sure you want to remove all tags from all {helpers.pluralize(len(songs), 'song')}? [y/n] "
                ).lower()
                == "y"
            ):
                for song in songs:
                    song.tags.clear()

                click.secho(
                    f"Removed all tags from all {helpers.pluralize(len(songs), 'song')}.",
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
    "-a",
    "--artist",
    "artists",
    help="Filter by artist.",
    multiple=True,
)
@click.option(
    "-b",
    "--album",
    "albums",
    help="Filter by album.",
    multiple=True,
)
@click.option(
    "-c",
    "--album-artist",
    "album_artists",
    help="Filter by album artist.",
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
    type=helpers.CLICK_SONG,
    multiple=True,
    help="Play only this/these song(s) (can be passed multiple times, e.g. 'maestro play -o 1 -o 17'). TAGS arguments are ignored",
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
@click.option(
    "-S/-nS",
    "--stream/--no-stream",
    "stream",
    default=False,
    help="Stream to maestro-music.vercel.app/listen-along/[USERNAME].",
)
@click.option(
    "-Y/-nY",
    "--lyrics/--no-lyrics",
    "lyrics",
    default=False,
    help="Show lyrics.",
)
@click.option(
    "-T/-nT",
    "--translated-lyrics/--no-translated-lyrics",
    "translated_lyrics",
    default=False,
    help="Show translated lyrics (ignored if '-Y/--lyrics' is not passed).",
)
@click.option(
    "-X/-nX",
    "--combine-artists/--no-combine-artists",
    "combine_artists",
    default=True,
    is_flag=True,
    help="Count artists as album artists and vice versa.",
)
def play(
    tags,
    exclude_tags,
    artists,
    albums,
    album_artists,
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
    lyrics,
    translated_lyrics,
    combine_artists,
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
    \x1b[1mUP/DOWN\x1b[0m\tto scroll through the queue/lyrics (mouse scrolling should also work)
    \x1b[1mSHIFT+UP/DOWN\x1b[0m\tmove the selected song up/down in the queue
    \x1b[1mENTER\x1b[0m\tplay the selected song/seek to selected lyric
    \x1b[1mp\x1b[0m\t\tsna[p] back to the currently [p]laying song/lyric
    \x1b[1mg\x1b[0m\t\tgo to the next pa[g]e/loop of the queue (ignored if not repeating queue)
    \x1b[1mBACKSPACE/DELETE\x1b[0m\tdelete the selected (not necessarily currently playing!) song from the queue
    \x1b[1md\x1b[0m\t\ttoggle [D]iscord rich presence
    \x1b[1ma\x1b[0m\t\t[a]dd a song to the end of the queue (opens a prompt to enter the song name or ID: ENTER to confirm, ESC to cancel)
    \x1b[1mi\x1b[0m\t\t[i]nsert a song in the queue after the selected song (opens a prompt like 'a')
    \x1b[1m,\x1b[0m\t\tadd ([comma]-separated) tag(s) to all songs in the queue. (opens a prompt like 'a')
    \x1b[1ms\x1b[0m\t\ttoggle [s]tream (streams to maestro-music.vercel.app/listen-along/[USERNAME]), requires login
    \x1b[1my\x1b[0m\t\ttoggle l[y]rics
    \x1b[1mt\x1b[0m\t\ttoggle [t]ranslated lyrics (if available, ignored if lyrics mode is off)
    \x1b[1m{\x1b[0m\t\tfocus playlist
    \x1b[1m}\x1b[0m\t\tfocus lyrics
    \x1b[1mSHIFT+LEFT/RIGHT[0m\tincrease/decrease width of lyrics window
    \x1b[1mo\x1b[0m\t\trel[o]ad song data (useful if you've changed e.g lyrics, tags, or metadata while playing)
    \x1b[1m?\x1b[0m\t\ttoggle this help message
    \x1b[1mf\x1b[0m\t\t[f]ind a song in the queue (opens a prompt like 'a')

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
    exclude_tags = set(exclude_tags)

    if only:
        playlist = list(only)
    else:
        playlist.extend(
            helpers.filter_songs(
                set(tags),
                exclude_tags,
                artists,
                albums,
                album_artists,
                match_all,
                combine_artists,
            )
        )

    # song files not found
    songs_not_found: list[helpers.Song] = []
    for i in range(len(playlist)):
        if not os.path.exists(playlist[i].song_path):
            songs_not_found.append(playlist[i])
            playlist[i] = None

    playlist: list[helpers.Song] = sorted(
        list(filter(lambda song: song is not None, playlist)),
        key=lambda song: song.song_id,
    )

    helpers.bounded_shuffle(playlist, shuffle_)
    if reverse:
        playlist.reverse()

    if not playlist:
        click.secho("No songs found matching criteria.", fg="red")
    else:
        from keyring.errors import NoKeyringError

        try:
            username = helpers.get_username()
            password = helpers.get_password()
            if stream:
                if username is None or password is None:
                    if username is None:
                        click.secho("Username not found.", fg="red")
                    if password is None:
                        click.secho("Password not found.", fg="red")
                    click.secho(
                        "Please log in using 'maestro login' to stream.",
                        fg="red",
                    )
                    return
            elif discord:
                if username is None or password is None:
                    if username is None:
                        click.secho("Username not found.", fg="yellow")
                    if password is None:
                        click.secho("Password not found.", fg="yellow")
                    click.secho(
                        "Log in using 'maestro login' to enable album art in the Discord rich presence.",
                        fg="yellow",
                    )
                    username = None
                    password = None
        except NoKeyringError as e:
            if stream:
                click.secho(
                    f"No keyring available. Cannot stream without login.\n{e}",
                    fg="red",
                )
            if discord:
                click.secho(
                    f"No keyring available. Cannot show album art in Discord rich presence without login.\n{e}",
                    fg="yellow",
                )
            username = None
            password = None

        curses.wrapper(
            _play,
            playlist,
            volume,
            loop,
            clips,
            reshuffle,
            discord,
            visualize,
            stream,
            username,
            password,
            lyrics,
            translated_lyrics and lyrics,
        )

    if songs_not_found:
        click.secho("Song files not found:", fg="red")
        for song in songs_not_found:
            click.secho(f"\t{song.song_path} (ID {song.song_id})", fg="red")


@cli.command()
@click.option(
    "-T/-nT",
    "--tag/--no-tag",
    "renaming_tag",
    default=False,
    help="If passed, rename tag instead of song (treat the arguments as tags).",
)
# NOTE: original is not forced to be a int so that tags can be renamed
@click.argument("original")
@click.argument("new_name")
def rename(original, new_name, renaming_tag):
    """
    Rename a song or tag.

    Renames the song with the ID ORIGINAL to NEW_NAME. The extension of the
    song (e.g. '.wav', '.mp3') is preserved—do not include it in the name.

    If the '-T/--tag' flag is passed, treats ORIGINAL as a tag, renaming all
    ocurrences of it to NEW_NAME—doesn't check if the tag NEW_NAME already
    exists, so be careful!
    """
    if not renaming_tag:
        original = helpers.CLICK_SONG(original)
        original_song_title = original.song_title
        original.song_title = new_name
        click.secho(
            f'Renamed song "{original_song_title}" (ID: {original.song_id}) to "{new_name}".',
            fg="green",
        )
    else:
        for song in helpers.SONGS:
            if original in song.tags:
                song.tags.remove(original)
                song.tags.add(new_name)

        click.secho(
            f"Renamed all ocurrences of tag '{original}' to '{new_name}'.",
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
    """Search for song names (or tags with '-T/--tag' flag). All songs/tags
    starting with PHRASE will appear before songs/tags containing but not
    starting with PHRASE. This search is case-insensitive."""
    if not searching_for_tags:
        results = helpers.search_song(phrase)
        if not any(results):
            click.secho("No results found.", fg="red")
            return

        for song in sum(results, []):
            helpers.print_entry(song, highlight=phrase)

        num_results = len(results[0]) + len(results[1]) + len(results[2])
        click.secho(
            f"Found {helpers.pluralize(num_results, 'song')}.",
            fg="green",
        )
    else:
        phrase = phrase.lower()
        results = (
            set(),
            set(),
            set(),
        )  # is, starts, contains but does not start
        for song in helpers.SONGS:
            for tag in song.tags:
                tag_lower = tag.lower()
                if tag_lower == phrase:
                    results[0].add(tag)
                elif tag_lower.startswith(phrase):
                    results[1].add(tag)
                elif phrase in tag_lower:
                    results[2].add(tag)

        if not any(results):
            click.secho("No results found.", fg="red")
            return

        for tag in sum(map(list, results), []):
            tag = tag.replace(phrase, click.style(phrase, fg="yellow"), 1)
            click.echo(tag)

        num_results = len(results[0]) + len(results[1]) + len(results[2])
        click.secho(
            f"Found {helpers.pluralize(num_results, 'tag')}.", fg="green"
        )


@cli.command(name="list")
@click.argument("search_tags", metavar="TAGS", nargs=-1)
@click.option(
    "-e",
    "--exclude-tags",
    "exclude_tags",
    multiple=True,
    help="Exclude songs/tags matching these tags.",
)
@click.option(
    "-s",
    "--sort",
    "sort_",
    type=click.Choice(
        (
            "none",
            "name",
            "n",
            "secs-listened",
            "s",
            "duration",
            "d",
            "times-listened",
            "t",
            "artist",
            "a",
            "album",
            "b",
            "album-artist",
            "c",
        )
    ),
    help="Sort by song name, seconds listened, duration or times listened (seconds listened divided by song duration). Increasing order, default is by ID for songs and no order for tags.",
    default="none",
    show_default=True,
)
@click.option(
    "-R/-nR",
    "--reverse/--no-reverse",
    "reverse_",
    default=False,
    help="Reverse the sorting order (decreasing instead of increasing). For example, 'maestro list -s s -R -t 5' will show the top 5 most-listened songs by seconds listened.",
)
@click.option(
    "-T/-nT",
    "--list-tags/--no-list-tags",
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
    help="Shows songs that match all criteria instead of any criteria. Ignored if '-t/--tag' is passed.",
)
@click.option(
    "-a",
    "--artist",
    "artists",
    multiple=True,
    help="Filter by artist(s) (fuzzy search); can pass multiple.",
)
@click.option(
    "-b",
    "--album",
    "albums",
    multiple=True,
    help="Filter by album (fuzzy search); can pass multiple.",
)
@click.option(
    "-c",
    "--album-artist",
    "album_artists",
    multiple=True,
    help="Filter by album artist (fuzzy search); can pass multiple.",
)
@click.option(
    "-A/-nA",
    "--list-artists/--no-list-artists",
    "listing_artists",
    is_flag=True,
    help="Show artists instead of songs.",
)
@click.option(
    "-B/-nB",
    "--list-albums/--no-list-albums",
    "listing_albums",
    is_flag=True,
    help="Show albums instead of songs.",
)
@click.option(
    "-C/-nC",
    "--list-album-artist/--no-list-album-artist",
    "listing_album_artists",
    is_flag=True,
    help="Show album artists instead of songs.",
)
@click.option(
    "-X/-nX",
    "--combine-artists/--no-combine-artists",
    "combine_artists",
    is_flag=True,
    default=True,
    help="Count artists as album artists and vice versa. Ignored if neither '-A/--list-artists' nor '-C/--list-album-artists' is passed.",
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
    artists,
    albums,
    album_artists,
    listing_artists,
    listing_albums,
    listing_album_artists,
    combine_artists,
):
    """List songs or tags.
    Output format: ID, name, duration, listen time, times listened, [clip-start, clip-end] if clip exists, comma-separated tags if any

    If the '-T/--list-tags' flag is passed, tags will be listed instead of songs.

    If any of the '-A/--list-artists', '-B/--list-albums', or
    '-C/--list-album-artists' flags are passed, the respective fields will be
    listed instead of songs.

    Output format: tag/artist/album/album artist, duration, listen time, times listened
    """
    if top is not None:
        if top < 1:
            click.secho(
                "The option '-t/--top' must be a positive number.", fg="red"
            )
            return

    if (
        sum(
            [
                listing_artists,
                listing_albums,
                listing_album_artists,
                listing_tags,
            ]
        )
        > 1
    ):
        click.secho(
            "Only one of '-A/--show-artist', '-B/--show-album', '-C/--show-album-artist', or '-T/--tag' can be passed.",
            fg="red",
        )
        return

    if year is None:
        year = "total"
    elif year == "cur":
        year = config.CUR_YEAR
    else:
        if not year.isdigit():
            click.secho("Year must be a number or 'cur'.", fg="red")
            return
        year = int(year)

    search_tags = set(search_tags)
    exclude_tags = set(exclude_tags)

    num_lines = 0

    if listing_tags:
        search_tags -= exclude_tags

        tags = defaultdict(lambda: [0, 0])
        for song in helpers.SONGS:
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
                    (
                        any(
                            album.lower() in song.album.lower()
                            for album in albums
                        )
                    ),
                    albums,
                ),
                (
                    (
                        any(
                            album_artist.lower()
                            in song.album_artist.lower()
                            + (
                                ", " + song.artist.lower()
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
                search_criteria = not search_criteria or all(search_criteria)
            else:
                search_criteria = not search_criteria or any(search_criteria)

            for tag in song.tags:
                if (not search_tags or tag in search_tags) and search_criteria:
                    tags[tag][0] += song.listen_times[year]
                    tags[tag][1] += song.duration

        tags = list(tags.items())

        if sort_ != "none":
            if sort_ in ("name", "n"):
                sort_key = lambda t: t[0].lower()
            elif sort_ in ("secs-listened", "s"):
                sort_key = lambda t: t[1][0]
            elif sort_ in ("duration", "d"):
                sort_key = lambda t: t[1][1]
            elif sort_ in ("times-listened", "t"):
                sort_key = lambda t: t[1][0] / t[1][1]
            tags.sort(key=sort_key)
            if reverse_:
                tags.reverse()

        for tag, (listen_time, total_duration) in tags:
            click.echo(
                f"{tag} {click.style(helpers.format_seconds(total_duration, show_decimal=True, digital=False), fg='bright_black')} {click.style(helpers.format_seconds(listen_time, show_decimal=True, digital=False), fg='yellow')} {click.style('%.2f'%(listen_time/total_duration), fg='green')}"
            )
            num_lines += 1
            if top is not None and num_lines == top:
                break
        return

    if listing_artists or listing_albums or listing_album_artists:
        abcs = defaultdict(lambda: [0, 0])
        if combine_artists:
            artists += album_artists
            album_artists = artists
        for song in helpers.filter_songs(
            search_tags,
            exclude_tags,
            artists,
            albums,
            album_artists,
            match_all,
            combine_artists,
        ):
            if listing_artists or (combine_artists and listing_album_artists):
                for artist in song.artist.split(", "):
                    if artists:
                        for search_artist in artists:
                            if search_artist.lower() in artist.lower():
                                abcs[artist][0] += song.listen_times[year]
                                abcs[artist][1] += song.duration
                                break
                    else:
                        abcs[artist][0] += song.listen_times[year]
                        abcs[artist][1] += song.duration
            if listing_albums:
                if albums:
                    for album in albums:
                        if album.lower() in song.album.lower():
                            abcs[album][0] += song.listen_times[year]
                            abcs[album][1] += song.duration
                else:
                    abcs[song.album][0] += song.listen_times[year]
                    abcs[song.album][1] += song.duration
            if listing_album_artists or (combine_artists and listing_artists):
                for album_artist in song.album_artist.split(", "):
                    if album_artists:
                        for search_album_artist in album_artists:
                            if (
                                search_album_artist.lower()
                                in album_artist.lower()
                            ):
                                abcs[album_artist][0] += song.listen_times[year]
                                abcs[album_artist][1] += song.duration
                                break
                    else:
                        abcs[album_artist][0] += song.listen_times[year]
                        abcs[album_artist][1] += song.duration

        abcs = list(abcs.items())

        if sort_ != "none":
            if sort_ in ("name", "n"):
                sort_key = lambda t: t[0].lower()
            elif sort_ in ("secs-listened", "s"):
                sort_key = lambda t: t[1][0]
            elif sort_ in ("duration", "d"):
                sort_key = lambda t: t[1][1]
            elif sort_ in ("times-listened", "t"):
                sort_key = lambda t: t[1][0] / t[1][1]
            abcs.sort(key=sort_key)
            if reverse_:
                abcs.reverse()

        for abc, (listen_time, total_duration) in abcs:
            click.echo(
                f"{abc} {click.style(helpers.format_seconds(total_duration, show_decimal=True, digital=False), fg='bright_black')} {click.style(helpers.format_seconds(listen_time, show_decimal=True, digital=False), fg='yellow')} {click.style('%.2f'%(listen_time/total_duration), fg='green')}"
            )
            num_lines += 1
            if top is not None and num_lines == top:
                break
        return

    songs = helpers.filter_songs(
        search_tags,
        exclude_tags,
        artists,
        albums,
        album_artists,
        match_all,
        combine_artists,
    )

    if sort_ == "none":
        sort_key = lambda song: song.song_id
    if sort_ in ("name", "n"):
        sort_key = lambda song: song.song_title.lower()
    elif sort_ in ("secs-listened", "s"):
        sort_key = lambda song: song.listen_times[year]
    elif sort_ in ("duration", "d"):
        sort_key = lambda song: song.duration
    elif sort_ in ("times-listened", "t"):
        sort_key = lambda song: song.listen_times[year] / song.duration
    songs.sort(key=sort_key, reverse=reverse_)

    no_results = True
    for song in songs:
        helpers.print_entry(song, year=year)
        num_lines += 1
        no_results = False
        if top is not None and num_lines == top:
            break

    if no_results and not any([search_tags, artists, albums, album_artists]):
        click.secho(
            "No songs found. Use 'maestro add' to add a song.", fg="red"
        )
    elif no_results:
        click.secho("No songs found matching criteria.", fg="red")


@cli.command()
@click.option(
    "-y",
    "--year",
    "year",
    help="Show time listened for a specific year, instead of the total. Passing 'cur' will show the time listened for the current year.",
)
@click.argument("songs", type=helpers.CLICK_SONG, nargs=-1, required=True)
def entry(songs, year):
    """
    View the details for specific song(s).

    \b
    Output format:
        ID, name, duration, listen time, times listened, [clip-start, clip-end] if clip exists, comma-separated tags if any
            artist - album (album artist)
    """
    if year is None:
        year = "total"
    elif year == "cur":
        year = config.CUR_YEAR
    else:
        if not year.isdigit():
            click.secho("Year must be a number.", fg="red")
            return
        year = int(year)

    for song in songs:
        helpers.print_entry(song, year=year)


@cli.command()
@click.argument("song", required=True)
@click.option(
    "-T/-nT",
    "--title/--no-title",
    "title",
    default=False,
    help="Treat SONG as a song title to search on YT Music instead of an existing maestro song.",
)
def recommend(song, title):
    """
    Get recommendations from YT Music based on song titles.

    Recommends songs (possibly explicit) using the YouTube Music API that are
    similar to SONG to listen to.

    If the '-T/--title' flag is passed, maestro directly searches up SONG on
    YouTube Music, rather than trying to find a matching entry in your maestro
    songs."""
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
        song = helpers.CLICK_SONG(song)
        results = ytmusic.search(
            os.path.splitext(song.song_title)[0], filter="songs"
        )

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


@cli.command(name="clips")
@click.argument("songs", required=True, type=helpers.CLICK_SONG, nargs=-1)
def clips_(songs: tuple[helpers.Song]):
    """
    List the clips for song(s).

    Output format: clip name: start time, end time

    The set clip for the song is bolded and highlighted in magenta.
    """
    for song in songs:
        if not song.clips:
            click.secho(
                f'No clips for "{song.song_title}" (ID {song.song_id}).',
            )
            continue
        click.echo("Clips for ", nl=False)
        click.secho(song.song_title, fg="blue", bold=True, nl=False)
        click.echo(f" (ID {song.song_id}):")

        def style_clip_name(clip_name, song):
            if clip_name == song.set_clip:
                return click.style(clip_name, bold=True, fg="magenta")
            else:
                return click.style(clip_name)

        if "default" in song.clips:
            click.echo(
                f"\t{style_clip_name('default', song)}: {song.clips['default'][0]}, {song.clips['default'][1]}"
            )
        for clip_name, (start, end) in song.clips.items():
            if clip_name == "default":
                continue
            click.echo(f"\t{style_clip_name(clip_name, song)}: {start}, {end}")


@cli.command(name="clip")
@click.argument("song", required=True, type=helpers.CLICK_SONG)
@click.argument("start", required=False, type=float, default=None)
@click.argument("end", required=False, type=float, default=None)
@click.option(
    "-n",
    "--name",
    "name",
    help="Name of the clip.",
    default="default",
)
@click.option(
    "-E/-nE",
    "--editor/--no-editor",
    "editor",
    default=True,
    help="Open the clip editor, even if START and END are passed. Ignored if neither START nor END are passed.",
)
def clip_(song: helpers.Song, name, start, end, editor):
    """
    Create or edit a clip for a song.

    Sets the clip (with name passed to '-n/--name' or 'default' if not passed)
    for SONG to the time range START to END (in seconds).

    If END is not passed, the clip will be from START to the end of the song.

    If neither START nor END are passed, a clip editor will be opened, in which
    you can move the start and end of the clip around using the arrow keys while
    listening to the song.

    If the '-E/--editor' flag is passed, the clip editor will be opened even if
    START and END are passed; this is useful if you want to fine-tune the clip.

    \b
    The editor starts out editing the start of the clip.
    \x1b[1mt\x1b[0m to toggle between editing the start and end of the clip.
    \x1b[1mLEFT/RIGHT\x1b[0m will move whichever clip end you are editing
        by 0.1 seconds, snap the current playback to that clip end (to exactly
        the clip start if editing start, end-1 if editing end), and pause.
    \x1b[1mSHIFT+LEFT/RIGHT\x1b[0m will move whichever clip end you are editing
        by 1 second, snap the current playback to that clip end, and pause.
    \x1b[1mSPACE\x1b[0m will play/pause.
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

    if start is None:  # clip editor
        start, end = curses.wrapper(helpers.clip_editor, song, name)
        if start is None:
            click.secho(
                f"No change in clip '{name}' for \"{song.song_title}\" (ID {song.song_id}).",
                fg="green",
            )
            return
        editor = False

        # hacky fix for end being past end of song sometimes
        end = min(end, song.duration)

    if end is None:
        end = song.duration
    if start > song.duration:
        click.secho("START must not be more than the song duration.", fg="red")
        return
    if end > song.duration:
        click.secho("END must not be more than the song duration.", fg="red")
        return
    if start > end:
        click.secho("START must not be more than END.", fg="red")
        return

    if editor:
        start, end = curses.wrapper(helpers.clip_editor, song, name, start, end)
        if start is None:
            click.secho(
                f"No change in clip '{name}' for \"{song.song_title}\" (ID {song.song_id}).",
                fg="green",
            )
            return

    if name in song.clips:
        click.secho(
            "Modified ",
            nl=False,
            fg="green",
        )
    else:
        click.secho(
            "Created ",
            nl=False,
            fg="green",
        )
    click.secho(
        f'clip "{name}" for "{song.song_title}" (ID {song.song_id}): {start} to {end}.',
        fg="green",
    )
    song.clips[name] = (start, end)


@cli.command()
@click.argument("songs", type=helpers.CLICK_SONG, nargs=-1, required=False)
@click.option(
    "-n",
    "--name",
    "names",
    help="Name(s) of the clip(s) to remove.",
    multiple=True,
)
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
def unclip(songs: tuple[helpers.Song], names, all_, force):
    """
    Remove clips from song(s).

    Removes any clips with names passed to '-n/--name' from each song in SONGS.
    If no names are passed, removes the clip 'default' from each song.

    If the '-A/--all' flag is passed, at most one of SONGS or '-n/--name' must
    be passed. If name(s) are passed, all clips with those names will be
    removed. If SONGS are passed, all clips for each song will be removed.
    Prompts for confirmation unless '-F/--force' is passed.
    """
    if all_:
        if songs and names:
            click.secho(
                "The '-A/--all' flag cannot be passed with both SONGS and '-n/--name'.",
                fg="red",
            )
            return

        if songs:
            if not force:
                click.echo(
                    f'Are you sure you want to remove all clips from {helpers.pluralize(len(songs), "song")}? This cannot be undone. [y/n] ',
                    nl=False,
                )
                if input().lower() != "y":
                    return
        elif names:
            if not force:
                click.echo(
                    f"Are you sure you want to remove all clips with names {', '.join(names)} for all songs? This cannot be undone. [y/n] ",
                    nl=False,
                )
                if input().lower() != "y":
                    return
            songs = helpers.SONGS
        else:
            click.secho(
                "The '-A/--all' flag must be passed with either SONGS or '-n/--name'.",
                fg="red",
            )
            return

    if not (songs or names):
        click.secho(
            "No songs or clip names passed—to remove all clips from all songs, pass the '-A/--all' flag.",
            fg="red",
        )
        return

    if not (names or all_):
        names = ("default",)

    for song in songs:
        if not names:
            song.clips.clear()
        else:
            for name in names:
                if name in song.clips:
                    del song.clips[name]

    if not names:
        click.secho(
            f"Removed all clips from {helpers.pluralize(len(songs), 'song')}.",
            fg="green",
        )
    else:
        click.secho(
            f"Removed {helpers.pluralize(len(names), 'clip', False)} {', '.join(map(repr, names))} from {helpers.pluralize(len(songs), 'song')}.",
            fg="green",
        )


@cli.command(name="set-clip")
@click.argument("songs", type=helpers.CLICK_SONG, nargs=-1, required=False)
@click.argument("name", required=True)
@click.option(
    "-F/-nF",
    "--force/--no-force",
    "force",
    default=False,
    help="Skip confirmation prompt.",
)
def set_clip(songs: tuple[helpers.Song], name, force):
    """
    Set the clip for song(s).

    Sets the clip for each song in SONGS to NAME; 'maestro play' will play this
    clip in clip mode.

    If no SONGS are passed, sets the clip for all songs. This prompts for
    confirmation unless '-F/--force' is passed.
    """
    if not songs:
        songs = helpers.SONGS
        if not force:
            click.echo(
                f"Are you sure you want to set the clip for all {helpers.pluralize(len(songs), 'song')} to '{name}'? This cannot be undone. [y/n] ",
                nl=False,
            )
            if input().lower() != "y":
                return

    for song in songs:
        song.set_clip = name

    click.secho(
        f"Set clip for {helpers.pluralize(len(songs), 'song')} to '{name}'.",
        fg="green",
    )


@cli.command()
@click.argument("songs", type=helpers.CLICK_SONG, required=True, nargs=-1)
@click.option("-m", "--metadata", "pairs", type=str, required=False)
@click.option(
    "-a",
    "--artist",
    help="Artist of the song. Overrides '-m/--metadata'.",
)
@click.option(
    "-b",
    "--album",
    help="Album of the song. Overrides '-m/--metadata'.",
)
@click.option(
    "-c",
    "--album-artist",
    help="Album artist of the song. Overrides '-m/--metadata'.",
)
def metadata(songs: tuple[helpers.Song], pairs, artist, album, album_artist):
    """
    View or edit the metadata for songs.

    If no options are passed, prints the metadata for each song in SONGS.

    If '-m/--metadata' is passed, sets the metadata for the each song in SONGS
    to the key-value pairs in -m/--metadata. The option should be passed as a
    string of the form 'key1:value1|key2:value2|...'.

    Possible editable metadata keys are: album, albumartist, artist, comment,
    compilation, composer, discnumber, genre, lyrics, totaldiscs, totaltracks,
    tracknumber, tracktitle, year, isrc
    """
    valid_pairs = None
    if any([artist, album, album_artist, pairs]):
        if pairs:
            pairs = [
                tuple(pair.strip().split(":", 1)) for pair in pairs.split("|")
            ]
        else:
            pairs = []

        valid_pairs = set(pairs[:])
        for key, value in pairs:
            if (
                key not in config.METADATA_KEYS
                or key.startswith("#")
                or key == "artwork"
            ):
                click.secho(
                    f"'{key}' is not a valid editable metadata key.",
                    fg="yellow",
                )
                valid_pairs.remove((key, value))
            elif key == "artist" and artist is not None:
                valid_pairs.remove((key, value))
            elif key == "album" and album is not None:
                valid_pairs.remove((key, value))
            elif key == "albumartist" and album_artist is not None:
                valid_pairs.remove((key, value))

        if artist is not None:
            valid_pairs.add(("artist", artist))
        if album is not None:
            valid_pairs.add(("album", album))
        if album_artist is not None:
            valid_pairs.add(("albumartist", album_artist))

        if not valid_pairs:
            click.secho("No valid metadata keys passed.", fg="red")
            return

        click.secho(f"Valid pairs: {valid_pairs}", fg="green")

    for song in songs:
        if not os.path.exists(song.song_path):
            click.secho(
                f'Song file "{song.song_title}" (ID {song.song_id}) not found.',
                fg="red",
            )
            continue

        if valid_pairs:
            for key, value in valid_pairs:
                song.set_metadata(key, value)
        else:
            click.echo("Metadata for ", nl=False)
            click.secho(song.song_title, fg="blue", bold=True, nl=False)
            click.echo(f" (ID {song.song_id}):")

            for key in config.METADATA_KEYS:
                try:
                    click.echo(
                        f"\t{key if not key.startswith('#') else key[1:]}: {song.get_metadata(key)}"
                    )
                except KeyError:
                    pass


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
        click.echo(config.settings["song_directory"])
        return

    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(config.SETTINGS_FILE, "rb+") as settings_file:
        settings = msgspec.json.decode(settings_file.read())
        settings["song_directory"] = directory

        settings_file.seek(0)
        settings_file.write(msgspec.json.encode(settings))
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
    Log in to maestro. Required for listen-along streaming and album covers in
    the Discord rich presence. The USERNAME argument is optional; if not passed,
    you will be prompted for your username.

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
    Log out of maestro.
    """
    if not force:
        click.echo("Are you sure you want to log out? [y/n] ", nl=False)
        if input().lower() != "y":
            return

    import keyring

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
    Create a new maestro account. Required for listen-along streaming and
    album covers in the Discord rich presence.

    The USERNAME argument is optional; if not passed, you will be prompted for
    a username.

    If the '-nL/--no-login' flag is passed, you will not be logged in after
    creating the account. You can still log in later using 'maestro login'.
    """
    helpers.signup(username, None, login_)


@cli.command(name="clear-logs")
def clear_logs():
    """
    Clear all logs stored by maestro.
    """
    try:
        os.remove(config.LOGFILE)
        try:
            rmtree(config.OLD_LOG_DIR)
        except FileNotFoundError:
            pass
        click.secho("Cleared logs.", fg="green")
    except FileNotFoundError:
        click.secho("No logs found.", fg="yellow")


@cli.command(name="download-ffmpeg")
def download_ffmpeg():
    """
    Download ffmpeg locally. A global or local FFmpeg install is required for
    clip editing.
    """
    from spotdl.utils.ffmpeg import download_ffmpeg as spotdl_download_ffmpeg

    spotdl_download_ffmpeg()


@cli.command()
def migrate():
    """
    Migrate the maestro database to the latest version.
    """
    if not os.path.exists(config.OLD_SONGS_INFO_PATH):
        click.secho(
            "Legacy files not found, no migration necessary.", fg="yellow"
        )
        return

    d = {}
    with open(config.OLD_SONGS_INFO_PATH, "r", encoding="utf-8") as f:
        for line in f.readlines():
            if not line.strip():
                continue
            details = line.split("|")

            song_id = details[0]
            song_file = details[1]
            tags = details[2].split(",")
            clip = list(map(float, details[3].split())) if details[3] else None
            d[song_id] = {
                "filename": song_file,
                "tags": tags,
                "clips": (
                    {
                        "default": clip,
                    }
                    if clip
                    else {}
                ),
                "stats": {},
            }

    for path in os.listdir(config.OLD_STATS_DIR):
        if not path.endswith(".txt"):
            continue

        with open(
            os.path.join(config.OLD_STATS_DIR, path), "r", encoding="utf-8"
        ) as f:
            year = os.path.splitext(path)[0]
            if year.isdigit():
                year = int(year)

            for line in f.readlines():
                if not line.strip():
                    continue
                details = line.split("|")

                song_id = details[0]
                stats = float(details[1])
                d[song_id]["stats"][year] = stats

    import safer

    with safer.open(config.SONGS_INFO_PATH, "wb") as f:
        f.write(msgspec.json.encode(d))

    # move old files to old-data
    old_data_dir = os.path.join(config.MAESTRO_DIR, "old-data/")
    os.makedirs(old_data_dir, exist_ok=True)
    move(config.OLD_SONGS_INFO_PATH, old_data_dir)
    move(config.OLD_STATS_DIR, old_data_dir)

    click.secho(
        f"Legacy files '{config.OLD_SONGS_INFO_PATH}' and '{config.OLD_STATS_DIR}' were moved to '{old_data_dir}', which can be safely deleted after confirming that all song data was moved to '{config.SONGS_INFO_PATH}'.",
        fg="green",
    )


@cli.command(name="format-data")
@click.argument("indent", type=int, default=4)
def format_data(indent: int):
    """
    Format the song data file to be more human-readable. The INDENT argument
    specifies the number of spaces to indent each level of the JSON file.
    """
    import safer

    with safer.open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as f:
        data = msgspec.json.decode(f.read())

    with open(config.SONGS_INFO_PATH, "wb") as f:
        f.write(msgspec.json.format(msgspec.json.encode(data), indent=indent))

    click.secho(
        f"Formatted '{config.SONGS_INFO_PATH}' with an indent of {indent}.",
        fg="green",
    )


@cli.command(name="lyrics")
@click.argument("songs", required=False, type=helpers.CLICK_SONG, nargs=-1)
@click.option(
    "-U/-nU",
    "--update/--no-update",
    "updating",
    default=False,
    help="Update lyrics for song(s).",
)
@click.option(
    "-R/-nR",
    "--remove/--no-remove",
    "removing",
    default=False,
    help="Remove lyrics for song(s).",
)
@click.option(
    "-O/-nO",
    "--override/--no-override",
    "override",
    default=True,
)
@click.option(
    "-T/-nT",
    "--translated/--no-translated",
    "translated",
    default=True,
)
@click.option(
    "-n", "--name", "name", help="Name to use instead of the song title."
)
@click.option(
    "-o",
    "--offset",
    "offset",
    type=float,
    default=0,
    help="Offset lyrics (secs); positive means later, negative means earlier.",
)
@click.option(
    "-F/-nF",
    "--force/--no-force",
    "force",
    default=False,
    help="Skip confirmation prompt.",
)
@click.option(
    "-A/-nA",
    "--all/--no-all",
    "all_",
    default=False,
    help="Update lyrics for all songs.",
)
def lyrics_(
    songs: tuple[helpers.Song],
    updating,
    removing,
    override,
    translated,
    name,
    offset,
    force,
    all_,
):
    """
    Display or update the lyrics for song(s). Shows the overridden lyrics if
    they exist instead of the embedded metadata lyrics. To view the embedded
    lyrics, you can use 'maestro metadata'. Any translated lyrics are also
    shown by default if available; turn them off with '-nT/--no-translated'.

    Updates (embedded metadata, not any overridden) lyrics if '-U/--update' is
    passed, downloading synced lyrics if available. If the song has lyrics,
    prompts for confirmation before updating unless '-F/--force' is passed.

    If '-R/--remove' is passed, removes the override lyrics for each song
    (prompts for confirmation). '-R/--remove' can only remove the overridden
    lyrics, not the embedded lyrics. Use 'maestro metadata -m "lyrics:"' to
    remove embedded lyrics.

    If '-A/--all' is passed, update/remove/view lyrics for all songs. Errors if
    SONGS are passed with '-A/--all'. Prompts for confirmation unless
    '-F/--force' is passed. Ignored if not updating.

    If the '-n/--name' flag is passed, uses NAME as the song title to search for
    lyrics instead of the actual song title. Ignored if not updating.

    If the '-o/--offset' flag is passed, offsets the lyrics by OFFSET seconds.
    Updates override lyrics if they exist by default; pass '-O/--no-override' to
    update only the embedded lyrics instead. Ignored if not updating.
    """
    if updating and removing:
        click.secho(
            "Cannot pass both '-U/--update' and '-R/--remove'.",
            fg="red",
        )
        return

    if len(songs) > 1 and name:
        click.secho(
            "Cannot pass a name when updating lyrics for multiple songs.",
            fg="red",
        )
        return
    if not (songs or all_):
        click.secho(
            "No songs passed. Use '-A/--all' to update lyrics for all songs.",
            fg="red",
        )
        return
    if songs and all_:
        click.secho(
            "Cannot pass songs with '-A/--all'.",
            fg="red",
        )
        return

    if all_:
        if not force:
            click.echo(
                f"Are you sure you want to {'update override' if updating else ('remove override' if removing else ('show' if not offset else 'offset the'))} lyrics for all songs? [y/n] ",
                nl=False,
            )
            if input().lower() != "y":
                return
        songs = helpers.SONGS
        force = True

    if not (updating or removing):  # viewing
        if offset:
            songs_valid = set(songs)
            for song in songs:
                parsed_lyrics = song.parsed_lyrics
                parsed_override_lyrics = song.parsed_override_lyrics
                embedded_is_timed = helpers.is_timed_lyrics(parsed_lyrics)
                override_is_timed = helpers.is_timed_lyrics(
                    parsed_override_lyrics
                )
                if not (embedded_is_timed or override_is_timed):
                    click.secho(
                        f'No timed lyrics found for "{song.song_title}" (ID: {song.song_id}).',
                        fg="yellow",
                    )
                    songs_valid.remove(song)
                    continue

                if embedded_is_timed:
                    parsed_lyrics.offset += int(offset * 1000)
                    song.raw_lyrics = parsed_lyrics.toLRC()
                if override_is_timed:
                    parsed_override_lyrics.offset += int(offset * 1000)
                    song.raw_override_lyrics = parsed_override_lyrics.toLRC()
            click.secho(
                f"Offset the lyrics for {helpers.pluralize(len(songs_valid), 'song')} by {offset} seconds.",
                fg="green",
            )
            return

        for song in songs:
            show_lyrics = True
            lyrics = song.parsed_override_lyrics or song.parsed_lyrics
            translated_lyrics = song.parsed_translated_lyrics
            if lyrics is None and translated_lyrics is None:
                click.secho(
                    f'No lyrics found for "{song.song_title}" (ID: {song.song_id}).',
                    fg="yellow",
                )
                show_lyrics = False
            show_translated = translated and translated_lyrics is not None

            if show_lyrics and show_translated:
                click.echo("Lyrics for ", nl=False)
                click.secho(song.song_title, fg="blue", bold=True, nl=False)
                click.echo(f" (ID {song.song_id}):")

                is_timed = helpers.is_timed_lyrics(lyrics)
                for i in range(len(lyrics)):
                    time_str = ""
                    if is_timed:
                        time_str = f"\t[{helpers.format_seconds(lyrics[i].time, show_decimal=True)}] "
                        click.secho(
                            f"{time_str}{lyrics[i].text}",
                            fg="cyan",
                        )
                    else:
                        click.secho(
                            "\t" + lyrics[i],
                            fg="cyan",
                        )
                    if i < len(translated_lyrics):
                        click.echo(
                            "\t"
                            + " " * len(time_str)
                            + helpers.get_lyric(translated_lyrics[i]),
                        )
            elif show_lyrics:
                helpers.display_lyrics(lyrics, song)
            elif show_translated:
                helpers.display_lyrics(
                    translated_lyrics,
                    song,
                    "translated",
                )
        return

    import syncedlyrics

    for song in songs:
        if removing:
            if override:
                if not force:
                    click.echo(
                        f'Are you sure you want to remove override lyrics for "{song.song_title}" (ID {song.song_id})? This cannot be undone. [y/n] ',
                        nl=False,
                    )
                if force or input().lower() == "y":
                    song.raw_override_lyrics = None
                    click.secho(
                        f'Removed override lyrics for "{song.song_title}" (ID {song.song_id}).',
                        fg="green",
                    )
            if translated:
                if not force:
                    click.echo(
                        f'Are you sure you want to remove translated lyrics for "{song.song_title}" (ID {song.song_id})? This cannot be undone. [y/n] ',
                        nl=False,
                    )
                if force or input().lower() == "y":
                    song.raw_translated_lyrics = None
                    click.secho(
                        f'Removed translated lyrics for "{song.song_title}" (ID {song.song_id}).',
                        fg="green",
                    )
            continue

        song_title = name or f"{song.artist} - {song.song_title}"

        if song.raw_lyrics:
            if not force:
                click.echo(
                    f'Lyrics already exist for "{song.song_title}" (ID {song.song_id}). Overwrite? [y/n] ',
                    nl=False,
                )
                if input().lower() != "y":
                    continue

        try:
            lyrics = syncedlyrics.search(song_title, allow_plain_format=True)
        except TypeError as e:
            print_to_logfile(
                f"TypeError with allow_plain_format=True in syncedlyrics.search: {e}"
            )
            try:
                lyrics = syncedlyrics.search(song_title)
            except Exception as f:
                click.secho(
                    f'Failed to download lyrics for "{song_title}": {f}',
                    fg="red",
                )
        except Exception as e:
            click.secho(
                f'Failed to download lyrics for "{song_title}": {e}',
                fg="red",
            )
        else:
            if lyrics:
                click.secho(
                    f'Downloaded lyrics for "{song.song_title}" (ID {song.song_id})'
                    + (f' using name "{name}"' if name else "")
                    + ".",
                    fg="green",
                )
                song.raw_lyrics = lyrics
            else:
                click.secho(f'No lyrics found for "{song_title}".', fg="yellow")


@cli.command(name="translit")
@click.argument("songs", required=True, type=helpers.CLICK_SONG, nargs=-1)
@click.option(
    "-l",
    "--lang",
    type=click.Choice(("japanese", "german") + config.INDIC_SCRIPTS),
    help="Language-specific transliteration support.",
)
@click.option(
    "-S/-nS",
    "--save-override/--no-save-override",
    "override",
    default=False,
    help="Add override lyrics.",
)
@click.option(
    "-F/-nF",
    "--force/--no-force",
    "force",
    default=False,
    help="Skip confirmation prompt.",
)
def transliterate(songs, lang, override, force):
    """
    Romanize foreign-script song lyrics. This is NOT translation, but rather
    converting the script to a more readable form using the 'unidecode' package.
    For example, "తెలుగు" would be transliterated to "telugu".

    If '-S/--save-override' is passed, adds the transliterated lyrics as an
    override for each song to maestro's internal data (prompts for confirmation
    if override already exists unless '-F/--force' is passed). This retains the
    original lyric metadata while allowing maestro to display the transliterated
    lyrics instead in 'maestro play'.

    Unidecode is not perfect and may not work well with all languages; for
    example, 'ä' becomes 'a' instead of 'ae', and Japanese characters are
    treated as Chinese characters (although maestro uses 'pykakasi' as a
    workaround for Japanese).

    If you're having issues, you can try explicitly passing the "-l/--lang"
    option with either "japanese" or "german" to improve transliteration. The
    former will skip unidecode and use pykakasi only, while the latter will
    replace 'ä', 'ö', 'ü' with 'ae', 'oe', 'ue' before running unidecode.

    Indic scripts are also supported using the 'indic_transliteration' package:
    bengali, assamese, modi (i.e. Marathi), malayalam, devanagari, sinhala,
    tibetan, gurmukhi (i.e. Punjabi), tamil, balinese, thai, burmese, telugu,
    kannada, gujarati, urdu, lao, javanese, manipuri, oriya, khmer
    """
    if not songs:
        click.secho("No songs passed.", fg="red")
        return

    import re

    from unidecode import unidecode

    ja_regex = re.compile(
        "[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\uff00-\uff9f\u4e00-\u9faf\u3400-\u4dbf]"
    )

    for song in songs:
        lyrics = song.parsed_lyrics
        if lyrics is None:
            click.secho(
                f'No lyrics found for "{song.song_title}" (ID: {song.song_id}).',
                fg="red",
            )
            return

        if lang == "de":
            for i in range(len(lyrics)):
                helpers.set_lyric(
                    lyrics,
                    i,
                    helpers.get_lyric(lyrics[i])
                    .replace("ä", "ae")
                    .replace("ö", "oe")
                    .replace("ü", "ue"),
                )

        if lang == "ja" or ja_regex.search(song.raw_lyrics):
            from pykakasi import kakasi

            kks = kakasi()
            for i in range(len(lyrics)):
                helpers.set_lyric(
                    lyrics,
                    i,
                    " ".join(
                        [
                            t["hepburn"]
                            for t in kks.convert(helpers.get_lyric(lyrics[i]))
                        ]
                    ),
                )

        if lang in config.INDIC_SCRIPTS:
            from itertools import groupby

            from indic_transliteration import sanscript

            for i in range(len(lyrics)):
                transliterated = ""
                for is_indic, word in groupby(
                    helpers.get_lyric(lyrics[i]).split(),
                    lambda w: all(
                        c not in "abcdefghijklmnopqrstuvwxyz" for c in w.lower()
                    ),
                ):
                    word = " ".join(word)
                    if is_indic:
                        word = (
                            sanscript.transliterate(word, lang, "iast")
                            .replace("c", "ch")
                            .replace("ā", "aa")
                            .replace("t", "th")
                            .replace("ṭ", "t")
                            .replace("ī", "ee")
                            .replace("ū", "oo")
                            .replace("è", "e")
                            .replace("ò", "o")
                            .replace("ṣ", "sh")
                            .replace("ś", "sh")
                            .replace("ḍ", "d")
                            .replace("ṇ", "n")
                        )
                        word = re.sub(r"ṃ(?=\w)", "n", word)
                        word = word.replace("ṃ", "m")
                    transliterated += word
                helpers.set_lyric(lyrics, i, transliterated)

        if lang != "ja" and lang not in config.INDIC_SCRIPTS:
            for i in range(len(lyrics)):
                helpers.set_lyric(
                    lyrics, i, unidecode(helpers.get_lyric(lyrics[i]))
                )

        if override:
            if song.raw_override_lyrics is not None:
                if not force:
                    click.echo(
                        f'Override lyrics already exist for "{song.song_title}" (ID {song.song_id}), do you want to replace them? This action cannot be undone. [y/n] ',
                        nl=False,
                    )
                    if input().lower() != "y":
                        continue
            if helpers.is_timed_lyrics(lyrics):
                song.raw_override_lyrics = lyrics.toLRC()
            else:
                song.raw_override_lyrics = "\n".join(lyrics)
            click.secho(
                f'Added override lyrics for "{song.song_title}" (ID {song.song_id}).',
                fg="green",
            )
        else:
            helpers.display_lyrics(lyrics, song, "transliterated")


@cli.command()
@click.argument("songs", required=True, type=helpers.CLICK_SONG, nargs=-1)
@click.option(
    "-S/-nS",
    "--save/--no-save",
    "save_",
    default=False,
    help="Save translated lyrics.",
)
@click.option(
    "-f",
    "--from",
    "from_langs",
    help="Language(s) to translate from.",
    multiple=True,
    default=("auto",),
)
@click.option(
    "-t",
    "--to",
    "to_lang",
    help="Language to translate to.",
    default="English",
)
@click.option(
    "-F/-nF",
    "--force/--no-force",
    "force",
    default=False,
    help="Skip confirmation prompt.",
)
@click.option(
    "-R/-nR",
    "--remove/--no-remove",
    "remove_",
    default=False,
    help="Remove translated lyrics.",
)
def translate(songs, save_, from_langs, to_lang, force, remove_):
    """
    Translate song lyrics using the 'translatepy' package.

    If '-S/--save' is passed, saves the translated lyrics to be used by 'maestro
    play' (displayed with original lyrics). If a translated lyric file already
    exists, prompts for confirmation before overwriting unless '-F/--force' is
    passed.

    If '-R/--remove' is passed, removes the translated lyrics for each song
    (prompts for confirmation unless '-F/--force' is passed).

    Default translation is from 'auto' to 'English', but you can specify the
    languages using the '-f/--from' and '-t/--to' options. Multiple '-f/--from'
    options can be passed, and 'maestro translate' will attempt to detect the
    language of each word/phrase. The first language in '-f/--from' is used as
    the default language if a word/phrase is detected as a language that was not
    passed.
    """
    if not songs:
        click.secho("No songs passed.", fg="red")
        return

    if remove_ and save_:
        click.secho(
            "Cannot pass both '-R/--remove' and '-S/--save'.",
            fg="red",
        )
        return

    import translatepy.translators

    from itertools import groupby

    from translatepy import Translator, Language
    from translatepy.exceptions import TranslatepyException

    translator = Translator(
        [
            translatepy.translators.GoogleTranslateV2,
            translatepy.translators.GoogleTranslateV1,
            translatepy.translators.YandexTranslate,
            translatepy.translators.ReversoTranslate,
            translatepy.translators.DeeplTranslate,
            translatepy.translators.LibreTranslate,
            translatepy.translators.TranslateComTranslate,
            translatepy.translators.MyMemoryTranslate,
        ]
    )
    for i, service in enumerate(translator.services):
        # pylint: disable=protected-access
        translator._instantiate_translator(service, translator.services, i)

    AUTO_LANG = Language("auto")

    from_langs = list(from_langs)
    for i in range(len(from_langs)):
        from_langs[i] = Language(from_langs[i])

    to_lang = Language(to_lang)

    if len(from_langs) > 1:
        for lang in from_langs:
            if lang.id == AUTO_LANG.id:
                click.secho(
                    "Cannot pass 'auto' with other languages in '-f/--from'.",
                )
                return

    for song in songs:
        if remove_:
            song.parsed_translated_lyrics = None
            click.secho(
                f'Removed translated lyrics for "{song.song_title}" (ID {song.song_id}).',
                fg="green",
            )
            continue

        lyrics = song.parsed_lyrics
        if lyrics is None:
            click.secho(
                f'No lyrics found for "{song.song_title}" (ID: {song.song_id}).',
                fg="red",
            )
            return

        translated_lyrics = [helpers.get_lyric(lyric) for lyric in lyrics]
        for i in range(len(lyrics)):
            lyric = helpers.get_lyric(lyrics[i])
            if not lyric:
                continue

            if len(from_langs) == 1 and from_langs[0].id != AUTO_LANG.id:
                try:
                    translated_lyrics[i] = translator.translate(
                        lyric, to_lang, from_langs[0]
                    ).result
                except TranslatepyException as e:
                    print_to_logfile(f"TranslatepyException on {lyric}: {e}")
            else:
                words = [[w, "auto"] for w in lyric.split()]
                for word in words:
                    try:
                        word[1] = translator.language(word[0]).result
                        if from_langs[0].id != AUTO_LANG.id:
                            for lang in from_langs:
                                if lang.id == word[1].id:
                                    break
                            else:
                                word[1] = from_langs[0]
                    except TranslatepyException as e:
                        print_to_logfile(
                            f"TranslatepyException on {word[0]}: {e}"
                        )

                translated_lyrics[i] = ""
                for lang, phrase in groupby(words, lambda x: x[1].id):
                    phrase = " ".join([w[0] for w in list(phrase)])
                    if lang != to_lang.id:
                        try:
                            phrase = translator.translate(
                                phrase, to_lang, lang
                            ).result
                        except TranslatepyException as e:
                            print_to_logfile(
                                f"TranslatepyException on {phrase}: {e}"
                            )
                        for service in translator.services:
                            service.clean_cache()
                    translated_lyrics[i] += phrase + " "

        if save_:
            if song.raw_translated_lyrics is not None:
                if not force:
                    click.echo(
                        f'Translated lyrics already exist for "{song.song_title}" (ID {song.song_id}), do you want to replace them? This action cannot be undone. [y/n] ',
                        nl=False,
                    )
                    if input().lower() != "y":
                        continue
            song.raw_translated_lyrics = "\n".join(translated_lyrics).strip()
            click.secho(
                f'Added translated lyrics for "{song.song_title}" (ID {song.song_id}).',
                fg="green",
            )
        else:
            helpers.display_lyrics(lyrics, song, "translated")


@cli.command()
def user():
    """
    Display the currently logged-in user.
    """
    import keyring

    try:
        click.echo(keyring.get_password("maestro-music", "username"))
        try:
            keyring.get_password("maestro-music", "password")
        except keyring.errors.KeyringError:
            click.secho("No password saved.", fg="red")
    except keyring.errors.KeyringError:
        click.secho("No user logged in.", fg="yellow")


if __name__ == "__main__":
    # check if frozen
    if getattr(sys, "frozen", False):
        multiprocessing.freeze_support()

    # click passes ctx, no param needed
    cli()  # pylint: disable=no-value-for-parameter
