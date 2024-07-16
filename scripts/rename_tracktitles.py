"""
Rename the 'tracktitle' metadata property of all songs to the title of the song.
Sufficiently new versions of maestro will automatically do this when adding and
renaming songs.

Usage: python rename_tracktitles.py <path_to_songs_directory>
"""

import os
import sys

import music_tag


DIR = sys.argv[1]  # REPLACE WITH THE PATH TO YOUR SONGS DIRECTORY

for path in os.listdir(DIR):
    fname, ext = os.path.splitext(path)
    if ext not in (".mp3", ".flac", ".ogg", ".wav"):
        continue

    m = music_tag.load_file(os.path.join(DIR, path))
    m["tracktitle"] = fname
    m.save()
