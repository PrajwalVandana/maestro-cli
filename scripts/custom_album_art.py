import json
import os
import subprocess

import music_tag
import requests

from yt_dlp import YoutubeDL


remove_paths = [
    "/Users/sysadmin/.maestro-files/songs/Aa Ammayi Gurinchi Meeku Cheppali Credits Song.mp3",
]
youtubeURLs = {
    "/Users/sysadmin/.maestro-files/songs/Thaaney Vachhindhanaa.mp3": "https://music.youtube.com/watch?v=LsZnqhNIMAc&si=EVe7OsmkWSE29Zjx",
    "/Users/sysadmin/.maestro-files/songs/U Turn.mp3": "https://music.youtube.com/watch?v=efIqLlcp_q8&si=pnQcmsYDQrecWbxv",
    "/Users/sysadmin/.maestro-files/songs/Vikram Rathore BGM.mp3": "https://music.youtube.com/watch?v=4qNaUvhwI38&si=uLivnUE8ofU_zIVK",
    "/Users/sysadmin/.maestro-files/songs/Weak.mp3": "https://music.youtube.com/watch?v=iD4h_naiHxg&si=WulbhShv9UugIpNz",
    "/Users/sysadmin/.maestro-files/songs/What Was.mp3": "https://music.youtube.com/watch?v=r3XG0c8b8i4&si=VXSQKGRDGExxBUcT",
}
spotifyURLs = {}


def yt_embed_artwork(path_, yt_dlp_info):
    yt_dlp_info["thumbnails"].sort(key=lambda d: d["preference"])
    best_thumbnail = yt_dlp_info["thumbnails"][-1]  # default thumbnail

    if "width" not in best_thumbnail:
        # diff so that any square thumbnail is chosen
        best_thumbnail["width"] = 0
        best_thumbnail["height"] = -1

    for thumbnail in yt_dlp_info["thumbnails"][:-1]:
        if "height" in thumbnail and (
            thumbnail["height"] == thumbnail["width"]
            and (
                best_thumbnail["width"]
                != best_thumbnail["height"]
            )
            or (
                thumbnail["height"] >= best_thumbnail["height"]
                and (
                    thumbnail["width"]
                    >= best_thumbnail["width"]
                )
                and (
                    (
                        best_thumbnail["width"]
                        != best_thumbnail["height"]
                    )
                    or thumbnail["width"] == thumbnail["height"]
                )
            )
        ):
            best_thumbnail = thumbnail

    image_url = best_thumbnail["url"]
    response = requests.get(image_url, timeout=5)
    image_data = response.content

    m_ = music_tag.load_file(path_)
    m_["artwork"] = image_data
    m_.save()

DIR = "/Users/sysadmin/.maestro-files/songs"
for path, url in spotifyURLs.items():
    subprocess.run(
        [
            "spotdl",
            "save",
            url,
            "--save-file",
            "temp.spotdl",
        ],
        check=True,
    )

    with open("temp.spotdl", "r") as f:  # pylint: disable=unspecified-encoding
        m = music_tag.load_file(os.path.join(DIR, path))
        m["artwork"] = requests.get(
            json.load(f)[0]["cover_url"], timeout=5
        ).content
        m.save()

for path, url in youtubeURLs.items():
    with YoutubeDL() as ydl:
        info = ydl.extract_info(url, download=False)
        yt_embed_artwork(path, info)

for path in remove_paths:
    m = music_tag.load_file(path)
    m["artwork"] = None
    m.save()