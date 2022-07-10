import click
import os
import shutil


SONGS_DIR = 'songs/'


@click.group()
def cli():
    """A command line interface for playing music."""
    pass


@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.argument('tags', nargs=-1)
@click.option('-m', "-move", is_flag=True)
def add(path, tags, m):
    """Add a new song."""
    with open('songs.txt', 'a+') as songs_file:
        songs_file.seek(0)  # start reading from beginning

        lines = songs_file.readlines()
        if not lines:
            song_id = 0
        else:
            song_id = int(lines[-1].split()[0]) + 1

        song_name = os.path.split(path)[1]
        dest_path = os.path.join(SONGS_DIR, song_name)

        if m:
            shutil.move(path, dest_path)
        else:
            shutil.copy(path, dest_path)

        songs_file.write(f"{song_id} {song_name} {' '.join(tags)}\n")

        # songs_file.seek(0)
        # print(songs_file.readlines())
    click.secho(f"Added song '{song_name}' with id {song_id}", fg='green')


@cli.command()
def list():
    """List all songs (with tags)."""
    with open('songs.txt', 'r') as songs_file:
        click.echo(songs_file.read().strip())


@cli.command()
@click.argument('song_id', required=True, type=click.INT)
def remove(song_id):
    """Remove a song."""
    songs_file = open('songs.txt', 'r')
    lines = songs_file.readlines()
    for i in range(len(lines)):
        line = lines[i]
        details = line.split()
        if int(details[0]) == song_id:
            lines.pop(i)
            songs_file.close()
            songs_file = open('songs.txt', 'w')
            songs_file.write(''.join(lines))
            click.secho(
                f"Removed song '{details[1]}' with id {song_id}", fg='green')
            break
        elif details[0] > song_id:
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
    """Add tags to a song (passed as ID)."""
    if len(tags) > 0:
        songs_file = open('songs.txt', 'r')
        lines = songs_file.readlines()
        for i in range(len(lines)):
            line = lines[i]
            details = line.split()
            if int(details[0]) == song_id:
                lines[i] += ' '+' '.join(tags)
                songs_file = open('songs.txt', 'w')
                songs_file.write(''.join(lines))
                click.secho(
                    f"Added tags {tags} to song '{details[1]}' with id {song_id}", fg='green')
                break
            elif details[0] > song_id:
                click.secho(f'Song with id {song_id} not found', fg='red')
                break
        else:
            click.secho(f'Song with id {song_id} not found', fg='red')

        songs_file.close()
    else:
        click.secho('No tags passed', fg='gray')
