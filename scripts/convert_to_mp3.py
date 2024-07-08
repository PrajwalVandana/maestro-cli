# pylint: disable=unspecified-encoding

import os
import subprocess

new_data = []
DIR = "/Users/sysadmin/.maestro-files/songs"
with open("/Users/sysadmin/.maestro-files/songs.txt", "r") as f:
    for line in f:
        data = line.strip().split("|")
        fname, ext = os.path.splitext(data[1])
        if ext.lower() == ".mp3":
            new_data.append(line)
            continue
        data[1] = fname + ".mp3"

        subprocess.run(
            [
                "ffmpeg",
                "-i",
                os.path.join(DIR, fname + ext),
                os.path.join(DIR, data[1]),
            ],
            check=True,
        )
        new_data.append("|".join(data))

with open("/Users/sysadmin/.maestro-files/songs.txt", "w") as f:
    f.write("\n".join(new_data))
