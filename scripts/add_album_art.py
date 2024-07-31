"""
Add album art to songs that don't have it, using the title of the song to search
Spotify for the album art. Can fail sometimes; the 'custom_album_art.py' script
offers more control over the process, but requires manual non-CLI input.

Usage: python add_album_art.py <path_to_songs_directory>
"""

import json
import os
import sys
import subprocess

import music_tag
import requests


DIR = sys.argv[1]  # REPLACE WITH THE PATH TO YOUR SONGS DIRECTORY

for path in os.listdir(DIR):
    fname, ext = os.path.splitext(path)
    if ext not in (".mp3", ".flac", ".ogg", ".wav"):
        continue

    m = music_tag.load_file(os.path.join(DIR, path))
    if m["artwork"]:
        continue

    subprocess.run(
        [
            "spotdl",
            "save",
            fname,
            "--save-file",
            "temp.spotdl",
        ],
        check=True,
    )

    with open("temp.spotdl", "r") as f:  # pylint: disable=unspecified-encoding
        m["artwork"] = requests.get(
            json.load(f)[0]["cover_url"], timeout=5
        ).content
        m.save()
