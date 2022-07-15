from time import sleep
from shutil import copy, move
from random import shuffle
import os
import multiprocessing
import click

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
from pygame import mixer  # NOQA

if os.name != 'nt':
    from getch import getch as posix_getch


MAESTRO_DIR = os.path.join(os.path.expanduser('~'), ".maestro-files/")
SONGS_DIR = os.path.join(MAESTRO_DIR, "songs/")
SONGS_INFO_PATH = os.path.join(MAESTRO_DIR, "songs.txt")
SCRUB_TIME = 5000
EXTS = ['.mp3']


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
def cli():
    """A command line interface for playing music."""
    if not os.path.exists(MAESTRO_DIR):
        os.mkdir(MAESTRO_DIR)
        os.mkdir(SONGS_DIR)
        f = open(SONGS_INFO_PATH, "x")
        f.close()
    else:
        if not os.path.exists(SONGS_DIR):
            os.mkdir(SONGS_DIR)
        if not os.path.exists(SONGS_INFO_PATH):
            f = open(SONGS_INFO_PATH, "x")
            f.close()


@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.argument('tags', nargs=-1)
@click.option('-m', "-move", "move_", is_flag=True,
              help="Move file from PATH to maestro's internal song database instead of copying.")
@click.option('-r', '-recursive', "recurse", is_flag=True,
              help="If PATH is a folder, add songs in subfolders.")
def add(path, tags, move_, recurse):
    """Add a new song, located at PATH. If PATH is a folder, adds all files
    in PATH (including files in subfolders if `-r` is passed). The name of each
    song will be the filename, with spaces replaced with '_' and the extension
    removed. Any spaces in tags will be replaced with '_'."""
    ext = os.path.splitext(path)[1]
    if not os.path.isdir(path) and ext not in EXTS:
        click.secho(f"'{ext}' is not supported", fg="red")
        return
    with open(SONGS_INFO_PATH, 'a+') as songs_file:
        songs_file.seek(0)  # start reading from beginning

        lines = songs_file.readlines()
        if not lines:
            song_id = 1
        else:
            song_id = int(lines[-1].split()[0]) + 1

        prepend_newline = lines and lines[-1][-1] != '\n'

        if os.path.isdir(path):
            if recurse:
                for dirpath, _, fnames in os.walk(path):
                    for fname in fnames:
                        if not fname.startswith('.'):
                            _add(os.path.join(dirpath, fname), tags, move_,
                                 songs_file, lines, song_id, prepend_newline)
                            prepend_newline = False
                            song_id += 1
            else:
                for fname in os.listdir(path):
                    if not fname.startswith('.'):
                        full_path = os.path.join(path, fname)
                        if os.path.isfile(full_path):
                            _add(full_path, tags, move_,
                                 songs_file, lines, song_id, prepend_newline)
                            prepend_newline = False
                            song_id += 1
        else:
            _add(path, tags, move_, songs_file,
                 lines, song_id, prepend_newline)


def _add(path, tags, move_, songs_file, lines, song_id, prepend_newline):
    song_name = os.path.split(path)[1].replace(' ', '_')
    dest_path = os.path.join(SONGS_DIR, song_name)

    for line in lines:
        details = line.split()
        if details[1] == song_name:
            click.secho(
                f"Song with name '{os.path.splitext(song_name)[0]}' already exists", fg="red")
            return

    if move_:
        move(path, dest_path)
    else:
        copy(path, dest_path)

    tags = [tag.replace(' ', '_') for tag in tags]

    if prepend_newline:
        songs_file.write('\n')
    songs_file.write(
        f"{song_id} {song_name}{' '+' '.join(tags) if tags else ''}\n")

    click.secho(
        f"Added song '{os.path.splitext(song_name)[0]}' with id {song_id}", fg='green')


@cli.command(name="list")
def list_():
    """List all songs (with IDs and tags)."""
    with open(SONGS_INFO_PATH, 'r') as songs_file:
        for line in songs_file:
            details = line.split()
            _print_entry(details)


@cli.command()
@click.argument('song_id', required=True, type=click.INT)
def remove(song_id):
    """Remove a song (passed as ID)."""
    songs_file = open(SONGS_INFO_PATH, 'r')
    lines = songs_file.read().splitlines()
    for i in range(len(lines)):
        line = lines[i]
        details = line.split()
        if int(details[0]) == song_id:
            lines.pop(i)
            songs_file.close()

            songs_file = open(SONGS_INFO_PATH, 'w')
            # line containing song to be removed has been removed
            songs_file.write('\n'.join(lines))

            song_name = details[1]
            os.remove(os.path.join(SONGS_DIR, song_name))  # remove actual song

            click.secho(
                f"Removed song '{os.path.splitext(song_name)[0]}' with id {song_id}", fg='green')

            break
        elif int(details[0]) > song_id:
            click.secho(f'Song with id {song_id} not found', fg='red')
            songs_file.close()
            break
    else:
        click.secho(f'Song with id {song_id} not found', fg='red')
        songs_file.close()


@cli.command()
@click.argument('song_id', type=click.INT, required=True)
@click.argument('tags', nargs=-1)
def add_tags(song_id, tags):
    """Add tags to a song (passed as ID). Any spaces in tags will be replaced
    with underscores ('_')."""
    if len(tags) > 0:
        songs_file = open(SONGS_INFO_PATH, 'r')
        lines = songs_file.read().splitlines()
        for i in range(len(lines)):
            line = lines[i]
            details = line.split()
            if int(details[0]) == song_id:
                new_tags = []
                for tag in tags:
                    tag = tag.replace(' ', '_')
                    if tag not in details[2:]:
                        new_tags.append(tag)
                lines[i] = ' '.join(details+new_tags)
                songs_file.close()

                songs_file = open(SONGS_INFO_PATH, 'w')
                songs_file.write('\n'.join(lines))
                click.secho(
                    f"Added tags {tags} to song '{os.path.splitext(details[1])[0]}' with id {song_id}",
                    fg='green'
                )
                break
            elif int(details[0]) > song_id:
                click.secho(f'Song with id {song_id} not found', fg='red')
                break
        else:
            click.secho(f'Song with id {song_id} not found', fg='red')

        songs_file.close()
    else:
        click.secho('No tags passed', fg='red')


@cli.command()
@click.argument('song_id', type=click.INT, required=True)
@click.argument('tags', nargs=-1)
def remove_tags(song_id, tags):
    """Remove tags from a song (passed as ID). Passing tags that the song
    doesn't have will not cause an error. Any spaces in tags will be replaced
    with underscores ('_')."""
    if len(tags) > 0:
        songs_file = open(SONGS_INFO_PATH, 'r')
        lines = songs_file.read().splitlines()
        for i in range(len(lines)):
            line = lines[i]
            details = line.split()
            if int(details[0]) == song_id:
                tags_to_keep = []
                for tag in details[2:]:
                    tag = tag.replace('_', ' ')
                    if tag not in tags:
                        tags_to_keep.append(tag)
                lines[i] = ' '.join(details[:2]+tags_to_keep)
                songs_file.close()

                songs_file = open(SONGS_INFO_PATH, 'w')
                songs_file.write('\n'.join(lines))
                click.secho(
                    f"Removed tags {tags} from song '{os.path.splitext(details[1])[0]}' with id {song_id}",
                    fg='green'
                )
                break
            elif int(details[0]) > song_id:
                click.secho(f'Song with id {song_id} not found', fg='red')
                break
        else:
            click.secho(f'Song with id {song_id} not found', fg='red')

        songs_file.close()
    else:
        click.secho('No tags passed', fg='red')


@cli.command()
@click.argument('tags', nargs=-1)
@click.option("-s", "-shuffle", "shuffle_", is_flag=True,
              help="Randomize order of songs when played.")
@click.option("-r", "-reverse", "reverse", is_flag=True,
              help="Play songs in reverse (most recently added first).")
@click.option("-o", "-only", "only", type=click.INT,
              help="Play only this song.")
def play(tags, shuffle_, reverse, only):
    """Play your songs. If tags are passed, any song matching any tag will be in
    your playlist. Any spaces in tags will be converted to underscores ('_').

    \b
    p  to pause
    g  to go back to previous song
    a  to play song again from beginning
    s  to skip to next song
    r  to rewind 5s
    f  to fast forward 5s
    e  to end the song player
    """
    playlist = []

    if only is not None:
        with open(SONGS_INFO_PATH, 'r') as songs_file:
            for line in songs_file:
                details = line.split()
                if int(details[0]) == only:
                    playlist.append(details[1])
                    break
            else:
                click.secho(f'Song with id {only} not found', fg='red')
                return
    else:
        if not tags:
            if not shuffle_ and not reverse:
                with open(SONGS_INFO_PATH, 'r') as songs_file:
                    for line in songs_file:
                        details = line.split()
                        playlist.append(details[1])
            else:
                with open(SONGS_INFO_PATH, 'r') as songs_file:
                    songs_dict = {}
                    for line in songs_file:
                        details = line.split()
                        songs_dict[int(details[0])] = details[1]

                    song_ids = list(songs_dict)
                    if shuffle_:
                        shuffle(song_ids)
                    else:  # reverse is True
                        song_ids.reverse()

                    for song_id in song_ids:
                        playlist.append(songs_dict[song_id])
        else:
            if not shuffle_ and not reverse:
                playlist = []
                with open(SONGS_INFO_PATH, 'r') as songs_file:
                    for line in songs_file:
                        details = line.split()
                        for tag in details[2:]:
                            tag = tag.replace(' ', '_')
                            if tag in tags:
                                playlist.append(details[1])
                                break
            else:
                with open(SONGS_INFO_PATH, 'r') as songs_file:
                    songs_dict = {}
                    for line in songs_file:
                        details = line.split()
                        for tag in details[2:]:
                            tag = tag.replace(' ', '_')
                            if tag in tags:
                                songs_dict[int(details[0])] = details[1]
                                break

                    song_ids = list(songs_dict)
                    if shuffle_:
                        shuffle(song_ids)
                    else:
                        song_ids.reverse()

                    for song_id in song_ids:
                        playlist.append(songs_dict[song_id])

    if not playlist:
        click.secho("No songs found matching criteria", fg="black")
    else:
        if os.name == 'nt':
            _play_win(playlist)
        else:
            _play_posix(playlist)


def output(i, playlist):
    return f"{click.style(os.path.splitext(playlist[i])[0], fg='blue', bold=True)} {click.style('%d/%d'%(i+1, len(playlist)), fg='blue')}" + click.style("\nNext up: "+os.path.splitext(playlist[i+1])[0] if i != len(playlist)-1 else '', fg="black")

def output_list(i, playlist):
    res = ""
    for j in range(len(playlist)):
        song_name = os.path.splitext(playlist[j])[
            0]+('\n' if j != len(playlist)-1 else '')
        if j != i:
            res += click.style(song_name, fg="black")
        else:
            res += click.style(song_name, fg="blue", bold=True)
    return res


def _play_win(playlist):  # NOTE: untested on Windows
    from msvcrt import kbhit as win_kbhit, getch as win_getch

    mixer.init()

    i = 0
    while i in range(len(playlist)):
        click.clear()
        click.echo(output(i, playlist))

        mixer.music.load(os.path.join(SONGS_DIR, playlist[i]))
        mixer.music.play()
        music_start_time = mixer.music.get_pos()

        next_song = 1  # -1 if going back, 0 if restarting, +1 if next song
        paused = False
        while True:
            if not mixer.music.get_busy() and not paused:
                next_song = 1
                break

            if not win_kbhit():
                c = win_getch()
                if c == 's':
                    if i == len(playlist)-1:
                        click.clear()
                        click.secho("No next song", fg="red")
                        sleep(2)
                        click.clear()
                        click.echo(output(i, playlist))
                    else:
                        next_song = 1
                        mixer.music.stop()
                        mixer.music.unload()
                        break
                elif c == 'g':
                    if i == 0:
                        click.clear()
                        click.secho("No previous song", fg="red")
                        sleep(2)
                        click.clear()
                        click.echo(output(i, playlist))
                    else:
                        next_song = -1
                        mixer.music.stop()
                        mixer.music.unload()
                        break
                elif c == 'a':
                    mixer.music.stop()
                    mixer.music.unload()
                    next_song = 0
                    break
                elif c == 'e':
                    mixer.music.stop()
                    mixer.music.unload()
                    return
                elif c == 'p':
                    if paused:
                        paused = False
                        mixer.music.unpause()
                    else:
                        paused = True
                        mixer.music.pause()
                elif c == 'r':
                    music_start_time = scrub(
                        mixer.music, -SCRUB_TIME, music_start_time)
                elif c == 'f':
                    music_start_time = scrub(
                        mixer.music, SCRUB_TIME, music_start_time)

        if next_song == -1:
            i -= 1
        elif next_song == 1:
            if i == len(playlist)-1:
                return
            i += 1


def posix_getch_wrapper(q):
    while True:
        c = posix_getch()
        q.put(c)


def _play_posix(playlist):
    chars_queue = multiprocessing.SimpleQueue()
    getch_process = multiprocessing.Process(
        target=posix_getch_wrapper, args=(chars_queue,))

    mixer.init()

    i = 0
    while i in range(len(playlist)):
        click.clear()
        click.echo(output(i, playlist))

        if not getch_process.is_alive():
            getch_process.start()

        mixer.music.load(os.path.join(SONGS_DIR, playlist[i]))
        mixer.music.play()
        # NOTE: mixer.music.get_pos()-music_start_time should return where the
        #       song is right now. Every time we rewind or fast forward, we
        #       change music_start_time accordingly
        music_start_time = mixer.music.get_pos()

        next_song = 1  # -1 if going back, 0 if restarting, +1 if next song
        paused = False
        while True:
            if not mixer.music.get_busy() and not paused:
                next_song = 1
                break

            if not chars_queue.empty():
                c = chars_queue.get()
                if c == 's':
                    if i == len(playlist)-1:
                        click.clear()
                        click.secho("No next song", fg="red")
                        sleep(2)
                        click.clear()
                        click.echo(output(i, playlist))
                    else:
                        next_song = 1
                        mixer.music.stop()
                        mixer.music.unload()
                        break
                elif c == 'g':
                    if i == 0:
                        click.clear()
                        click.secho("No previous song", fg="red")
                        sleep(2)
                        click.clear()
                        click.echo(output(i, playlist))
                    else:
                        next_song = -1
                        mixer.music.stop()
                        mixer.music.unload()
                        break
                elif c == 'a':
                    mixer.music.stop()
                    mixer.music.unload()
                    next_song = 0
                    break
                elif c == 'e':
                    mixer.music.stop()
                    mixer.music.unload()
                    getch_process.terminate()
                    return
                elif c == 'p':
                    if paused:
                        paused = False
                        mixer.music.unpause()
                    else:
                        paused = True
                        mixer.music.pause()
                elif c == 'r':
                    music_start_time = scrub(
                        mixer.music, -SCRUB_TIME, music_start_time)
                elif c == 'f':
                    music_start_time = scrub(
                        mixer.music, SCRUB_TIME, music_start_time)

        if next_song == -1:
            i -= 1
        elif next_song == 1:
            if i == len(playlist)-1:
                getch_process.terminate()
                return
            i += 1


def scrub(music_player, scrub_time, music_start_time):
    """Returns new value of `music_start_time`."""
    music_player.set_pos(
        (music_player.get_pos()-music_start_time+scrub_time)/1000)
    return music_start_time-scrub_time


@cli.command()
@click.argument('song_id', type=click.INT)
@click.argument('name')
def rename(song_id, name):
    """Renames the song with the id SONG_ID to NAME. Any spaces in NAME are
    replaced with underscores."""
    songs_file = open(SONGS_INFO_PATH, 'r')
    lines = songs_file.read().splitlines()
    for i in range(len(lines)):
        line = lines[i]
        details = line.split()
        if int(details[0]) == song_id:
            name = name.replace(' ', '_')

            old_name = details[1]
            details[1] = name + os.path.splitext(old_name)[1]

            lines[i] = ' '.join(details)
            songs_file.close()
            songs_file = open(SONGS_INFO_PATH, 'w')
            songs_file.write('\n'.join(lines))

            os.rename(os.path.join(SONGS_DIR, old_name), os.path.join(
                SONGS_DIR, details[1]))

            click.secho(
                f"Renamed song '{os.path.splitext(old_name)[0]}' with id {song_id} to '{os.path.splitext(details[1])[0]}'",
                fg='green'
            )

            break
        elif int(details[0]) > song_id:
            click.secho(f'Song with id {song_id} not found', fg='red')
            songs_file.close()
            break
    else:
        click.secho(f'Song with id {song_id} not found', fg='red')
        songs_file.close()


@cli.command()
@click.argument('phrase')
def search(phrase):
    """Searches for songs that containing PHRASE. All songs starting with PHRASE
    will appear before songs containing but not starting with PHRASE. If PHRASE
    contains spaces, they will be replaced with underscores. This search is
    case-insensitive."""
    phrase = phrase.replace(' ', '_').lower()
    with open(SONGS_INFO_PATH, 'r') as songs_file:
        results = [], []  # starts, contains but does not start
        for line in songs_file:
            song_id, song_name, *tags = line.split()
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
            details = line.split()
            if int(details[0]) in results[0]:
                _print_entry(details)

        songs_file.seek(0)
        for line in songs_file:
            details = line.split()
            if int(details[0]) in results[1]:
                _print_entry(details)


def _print_entry(entry):
    """`entry` should be passed as a list (what you get when you call
    `line.split()`)."""
    click.secho(entry[0]+' ', fg="black", nl=False)
    click.secho(os.path.splitext(entry[1])[0], fg="blue", nl=(len(entry) == 2))
    if len(entry) > 2:
        click.echo(' '+' '.join(entry[2:]))
