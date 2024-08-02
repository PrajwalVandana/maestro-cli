from os.path import normpath

from pkg_resources import parse_requirements
from setuptools import setup, find_packages


d = {}
with open(normpath("maestro/__version__.py"), encoding="utf-8") as f:
    exec(f.read(), d)  # pylint: disable=exec-used
VERSION = d["VERSION"]

with open("requirements.txt", "r", encoding="utf-8") as f:
    install_requires = [str(r) for r in parse_requirements(f)]

setup(
    name="maestro-music",
    version=VERSION,
    author="Prajwal Vandana",
    url="https://github.com/PrajwalVandana/maestro-cli",
    description="A simple command line tool to play songs (or any audio files, really).",
    long_description=open("readme.md", encoding="utf-8").read(),
    license="MIT",
    license_files=["LICENSE"],
    long_description_content_type="text/markdown",
    keywords=[
        "music",
        "sound",
        "audio",
        "music-player",
        "cli",
        "ogg",
        "vorbis",
        "ogg vorbis",
        "flac",
        "mp3",
        "wav",
        "spotify",
        "youtube",
        "audio-visualization",
        "audio-visualizer",
    ],
    packages=find_packages(include=["maestro"]),
    install_requires=install_requires,
    entry_points={
        "console_scripts": [
            "maestro = maestro.main:cli",
        ],
    },
)
