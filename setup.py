from setuptools import setup

MAC_DEPS = [
    dep + "; sys_platform == 'darwin'"
    for dep in [
        "pyobjc-core",
        "pyobjc-framework-ApplicationServices",
        "pyobjc-framework-AVFoundation",
        "pyobjc-framework-Cocoa",
        "pyobjc-framework-CoreAudio",
        "pyobjc-framework-CoreMedia",
        "pyobjc-framework-MediaPlayer",
        "pyobjc-framework-Quartz",
    ]
]

setup(
    name="maestro-music",
    version="1.0.11",
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
        "flac",
        "mp3",
        "wav",
        "spotify",
        "youtube",
        "audio-visualization",
        "audio-visualizer",
    ],
    py_modules=["maestro", "mac_presence", "icon", "helpers", "config"],
    install_requires=[
        "click",
        "just_playback",
        "music-tag",
        "pypresence",
        "yt-dlp",
        "spotdl",
        "ytmusicapi",
        "librosa",
        "numba",
        "numpy",
        "windows-curses; sys_platform == 'win32'",
    ]
    + MAC_DEPS,
    entry_points={
        "console_scripts": [
            "maestro = maestro:cli",
        ],
    },
)
