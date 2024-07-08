import json
import os
import subprocess

import music_tag
import requests


DIR = "/Users/sysadmin/.maestro-files/songs"
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
