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
        # latter is clip-agnostic, former is clip-aware
        player.duration = player.playback.duration

        player.update_metadata()
        player.playback.play()
        player.set_volume(volume)
        # print_to_logfile("Changed song", player.playback.curr_pos)  # DEBUG

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
                            # -1 because pos can be 0
                            next_song = -player.scroller.pos - 1
                            player.playback.stop()
                            break
                        elif c == curses.KEY_DC:
                            selected_song = player.scroller.pos
                            deleted_song = player.playlist[selected_song]
                            del player.playlist[selected_song]

                            if loop:
                                for i in range(len(next_playlist)):
                                    if next_playlist[i][0] == deleted_song:
                                        del next_playlist[i]
                                        break

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
                                    player.duration = player.playback.duration
                                player.update_screen()
                            elif ch in "pP":
                                player.scroller.pos = player.i
                                player.scroller.resize()
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
                                if player.update_discord:
                                    player.update_discord = False
                                    if player.discord_rpc is not None:
                                        player.discord_rpc.close()
                                    player.discord_connected = 0
                                else:

                                    def f():
                                        player.initialize_discord()
                                        player.update_discord_metadata()

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

                                player.update_screen()
                            elif ch in "vV":
                                player.visualize = not player.visualize
                                player.update_screen()
                            elif ch in "sS":
                                player.stream = not player.stream
                                if player.stream:
                                    if player.username is not None:
                                        threading.Thread(
                                            target=player.update_stream_metadata,
                                            daemon=True,
                                        ).start()
                                        player.ffmpeg_process.start()
                                else:
                                    player.ffmpeg_process.terminate()
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
                            if player.prompting[2] in (
                                config.PROMPT_MODES["add"],
                                config.PROMPT_MODES["insert"],
                            ):
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
                            elif (
                                "|" not in player.prompting[0]
                                and player.prompting[2]
                                == config.PROMPT_MODES["tag"]
                            ):
                                tags = set(player.prompting[0].split(","))

                                for song in player.playlist:
                                    song.tags |= tags

                                player.prompting = None
                                curses.curs_set(False)
                                player.scroller.resize(screen_size[0] - 2)

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
                1 / config.FPS if player.visualize else 1,
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

        player.song.listen_times[config.CUR_YEAR] += time_listened
        player.song.listen_times["total"] += time_listened
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
        elif next_song < -1:  # user pos -> - (pos + 1)
            player.i = -next_song - 1
        elif next_song == 2:
            next_next_playlist = next_playlist[:]
            if reshuffle:
                helpers.bounded_shuffle(next_next_playlist, reshuffle)
            player.playlist, next_playlist = (
                next_playlist,
                next_next_playlist,
            )
            player.i = 0
            player.scroller.pos = 0


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
        config.SETTINGS = config.DEFAULT_SETTINGS
        update_settings = True
    else:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
            s = f.read()
            if s:
                config.SETTINGS = msgspec.json.decode(s)
                for key in config.DEFAULT_SETTINGS:
                    if key not in config.SETTINGS:
                        config.SETTINGS[key] = config.DEFAULT_SETTINGS[key]
                        update_settings = True
            else:
                config.SETTINGS = config.DEFAULT_SETTINGS
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
    if not os.path.exists(config.SETTINGS["song_directory"]):
        os.makedirs(config.SETTINGS["song_directory"])

    t = time()
    if t - config.SETTINGS["last_version_sync"] > 24 * 60 * 60:  # 1 day
        config.SETTINGS["last_version_sync"] = t
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
        with open(config.SETTINGS_FILE, "wb") as g:
            g.write(msgspec.json.encode(config.SETTINGS))

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
    type=click.Choice(["wav", "mp3", "flac", "vorbis"]),
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
    "-nD/-D",
    "--skip-dupes/--no-skip-dupes",
    default=False,
    help="Skip adding song names that are already in the database. If not passed, 'copy' is appended to any duplicate names.",
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
    skip_dupes,
):
    """
    Add a new song.

    Adds the audio file located at PATH. If PATH is a folder, adds all files
    in PATH (including files in subfolders if '-r' is passed). The name of each
    song will be the filename (unless '-n' is passed).

    If the '-Y/--youtube' flag is passed, PATH is treated as a YouTube or
    YouTube Music URL instead of a file path.

    If the '-S/--spotify' flag is passed, PATH is treated as a Spotify
    track URL, album URL, playlist URL, artist URL, or search query instead of
    a file path.

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
                "Cannot pass both '-Y/--youtube' and '-S/--spotify' flags.",
                fg="red",
            )
            return

        if youtube:
            from spotdl.utils.ffmpeg import get_ffmpeg_path
            from yt_dlp import YoutubeDL

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
    if len(paths) > 1 and name is not None:
        click.secho(
            "Cannot pass '-n/--name' option when adding multiple songs.",
            fg="yellow",
        )

    if len(paths) == 1 and name is not None:  # renaming
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
                continue
        metadata_pairs = list(
            filter(lambda t: t[0] not in keys_to_ignore, metadata_pairs)
        )

    for path in paths:
        import music_tag

        ext = os.path.splitext(path)[1].lower()
        if not os.path.isdir(path) and ext not in config.EXTS:
            click.secho(f"'{ext}' is not supported.", fg="red")
            continue

        song_fname = os.path.split(path)[1]
        song_title = os.path.splitext(song_fname)[0]
        dest_path = os.path.join(config.SETTINGS["song_directory"], song_fname)

        for song in helpers.SONGS:
            if song.song_title == song_title:
                if skip_dupes:
                    click.secho(
                        f"Song with name '{song_title}' already exists, skipping.",
                        fg="yellow",
                    )
                    os.remove(path)
                    break
                click.secho(
                    f"Song with name '{song_title}' already exists, 'copy' will be appended to the song name.",
                    fg="yellow",
                )
                song_fname = song_title + " copy" + ext

                dest_path = os.path.join(
                    config.SETTINGS["song_directory"], song_fname
                )
                break

        if move_:
            move(path, dest_path)
        else:
            copy(path, dest_path)

        song_id = helpers.SONG_DATA.add_song(dest_path, tags)

        if not tags:
            tags_string = ""
        elif len(tags) == 1:
            tags_string = f" and tag '{tags[0]}'"
        else:
            tags_string = f" and tags {', '.join([repr(tag) for tag in tags])}"

        song_metadata = music_tag.load_file(dest_path)
        if metadata_pairs is not None:
            for path in paths:
                for key, value in metadata_pairs:
                    song_metadata[key] = value
                song_metadata.save()

        click.secho(
            f"Added song '{song_fname}' with ID {song_id}"
            + tags_string
            + f" and metadata (artist: {song_metadata['artist'] if song_metadata['artist'] else '<None>'}, album: {song_metadata['album'] if song_metadata['album'] else '<None>'}, albumartist: {song_metadata['albumartist'] if song_metadata['albumartist'] else '<None>'}).",
            fg="green",
        )


@cli.command()
@click.argument("args", required=True, nargs=-1)
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
                f'Removed song "{song.song_title}" with ID {song.song_id}.',
                fg="green",
            )
            song.remove_self()
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
def untag(songs, tags, all_):
    """Remove tags from songs. Tags that a song doesn't have will be ignored.

    Passing the '-A/--all' flag will remove all tags from each song, unless TAGS
    is passed (in which case the flag is ignored)."""
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
            for song in songs:
                song.tags.clear()

            click.secho(
                f"Removed all tags from {helpers.pluralize(len(songs), 'song')}.",
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
    \x1b[1ms\x1b[0m\t\ttoggle [s]tream (streams to maestro-music.vercel.app/listen/[USERNAME]), requires login

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
        if tags:
            tags = set(tags)
            for song in helpers.SONGS:
                if match_all and tags <= song.tags:
                    playlist.append(song)
                elif not match_all and tags & song.tags:
                    playlist.append(song)
        else:
            playlist = sorted(
                list(helpers.SONGS), key=lambda song: song.song_id
            )

        for i in range(len(playlist)):
            if exclude_tags & playlist[i].tags:
                playlist[i] = None

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
        click.secho("No songs found matching tag criteria.", fg="red")
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
        for song in helpers.SONGS:
            if song.song_title == original:
                song.song_title = new_name
                click.secho(
                    f"Renamed song '{original}' to '{new_name}'.", fg="green"
                )
                break
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
    help="Exclude songs (or tags if '-T/--tags' is passed) matching these tags.",
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
    "-A/-nA",
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
    """List songs or tags.

    Output format: ID, name, duration, listen time, times listened, [clip-start, clip-end] if clip exists, comma-separated tags if any

    If the '-T/--tag' flag is passed, tags will be listed instead of songs.

    Output format: tag, duration, listen time, times listened

    If TAGS are passed, all songs matching ANY tag in TAGS will be listed,
    unless the '-M/--match-all' flag is passed, in which case EVERY tag must
    be matched (this flag is ignored if listing tags).
    """
    if top is not None:
        if top < 1:
            click.secho(
                "The option '-t/--top' must be a positive number.", fg="red"
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

    if search_tags:
        search_tags = set(search_tags)
    if exclude_tags:
        exclude_tags = set(exclude_tags)

    num_lines = 0

    if listing_tags:
        tags = defaultdict(lambda: [0, 0])
        for song in helpers.SONGS:
            for tag in song.tags:
                if (
                    not search_tags
                    or tag in search_tags
                    and tag not in exclude_tags
                ):
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

    no_results = True
    songs = []
    for song in helpers.SONGS:
        if search_tags:
            if match_all:
                if not search_tags <= song.tags:  # subset
                    continue
            else:
                if not search_tags & song.tags:  # intersection
                    continue
        if exclude_tags:
            if exclude_tags & song.tags:
                continue

        songs.append(song)

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

    for song in songs:
        helpers.print_entry(song, year=year)
        num_lines += 1
        no_results = False
        if top is not None and num_lines == top:
            break

    if no_results and search_tags:
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
    Get recommendations from YT Music based on song titles (experimental).

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
    """
    for song in songs:
        if not song.clips:
            click.secho(
                f"No clips for \"{song.song_title}\" (ID {song.song_id}).",
            )
            continue
        click.echo("Clips for ", nl=False)
        click.secho(song.song_title, fg="blue", bold=True, nl=False)
        click.echo(f" with ID {song.song_id}:")

        if "default" in song.clips:
            click.echo(f"\tdefault: {song.clips['default'][0]}, {song.clips['default'][1]}")
        for clip_name, (start, end) in song.clips.items():
            if clip_name == "default":
                continue
            click.echo(f"{clip_name}: {start}, {end}")


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

    If the '-A/--all' flag is passed, exactly one of SONGS or '-n/--name' must
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
        click.secho(
            "No clip names passed. Pass the '-A/--all' flag to remove all clips from each song.",
            fg="red",
        )
        return

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
            f"Removed {helpers.pluralize(len(names), 'clip', False)} {', '.join(map(lambda n: f'\'{n}\'', names))} from {helpers.pluralize(len(songs), 'song')}.",
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
                f"Are you sure you want to set the clip for all {helpers.pluralize(len(helpers.SONGS), 'song')} to '{name}'? This cannot be undone. [y/n] ",
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
def metadata(songs: tuple[helpers.Song], pairs):
    """
    View or edit the metadata for songs.

    If the -m/--metadata option is not passed, prints the metadata for each song
    in SONGS.

    If the option is passed, sets the metadata for the each song in SONGS to the
    key-value pairs in -m/--metadata. The option should be passed as a
    string of the form 'key1:value1|key2:value2|...'.

    Possible editable metadata keys are: album, albumartist, artist, comment,
    compilation, composer, discnumber, genre, lyrics, totaldiscs, totaltracks,
    tracknumber, tracktitle, year, isrc

    Keys are not case sensitive and can contain arbitrary whitespace, '-', and
    '_' characters. In other words, 'Album Artist', 'album-artist', and
    'album_artist' are all synonyms for 'albumartist'. Also, 'disk' is
    synonymous with 'disc'.
    """

    if pairs:
        pairs = [tuple(pair.strip().split(":", 1)) for pair in pairs.split("|")]

        valid_pairs = pairs[:]
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
                continue

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

        if pairs:
            for key, value in valid_pairs:
                song.set_metadata(key, value)
        else:
            click.echo("Metadata for ", nl=False)
            click.secho(song.song_title, fg="blue", bold=True, nl=False)
            click.echo(f" with ID {song.song_id}:")

            for key in config.METADATA_KEYS:
                try:
                    click.echo(
                        f"\t{key if not key.startswith('#') else key[1:]}: {song.get_metadata(key).value}"
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
        click.echo(config.SETTINGS["song_directory"])
        return

    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(config.SETTINGS_FILE, "rb+", encoding="utf-8") as settings_file:
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
                details = line.split("|")

                song_id = details[0]
                stats = float(details[1])
                d[song_id]["stats"][year] = stats

    with open(config.SONGS_INFO_PATH, "wb") as f:
        f.write(msgspec.json.encode(d))

    # move old files to old_data
    old_data_dir = os.path.join(config.MAESTRO_DIR, "old_data/")
    os.makedirs(old_data_dir, exist_ok=True)
    move(config.OLD_SONGS_INFO_PATH, old_data_dir)
    move(config.OLD_STATS_DIR, old_data_dir)

    click.secho(
        f"Legacy files '{config.OLD_SONGS_INFO_PATH}' and '{config.OLD_STATS_DIR}' were moved to '{old_data_dir}', which can be safely deleted after confirming that all song data was moved to '{config.SONGS_INFO_PATH}'.",
        fg="green",
    )


@cli.command(name="format-data")
@click.argument("indent", type=int, default=2)
def format_data(indent: int):
    """
    Format the song data file to be more human-readable. The INDENT argument
    specifies the number of spaces to indent each level of the JSON file.
    """
    with open(config.SONGS_INFO_PATH, "r", encoding="utf-8") as f:
        data = msgspec.json.decode(f.read())

    with open(config.SONGS_INFO_PATH, "wb") as f:
        f.write(msgspec.json.format(msgspec.json.encode(data), indent=indent))


if __name__ == "__main__":
    # check if frozen
    if getattr(sys, "frozen", False):
        multiprocessing.freeze_support()

    # click passes ctx, no param needed
    cli()  # pylint: disable=no-value-for-parameter
