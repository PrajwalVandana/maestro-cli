from setuptools import setup

MAC_DEPS = [
    "pyobjc-core; sys_platform == 'darwin'",
    "pyobjc-framework-ApplicationServices; sys_platform == 'darwin'",
    "pyobjc-framework-AVFoundation; sys_platform == 'darwin'",
    "pyobjc-framework-Cocoa; sys_platform == 'darwin'",
    "pyobjc-framework-CoreAudio; sys_platform == 'darwin'",
    "pyobjc-framework-CoreMedia; sys_platform == 'darwin'",
    "pyobjc-framework-MediaPlayer; sys_platform == 'darwin'",
    "pyobjc-framework-Quartz; sys_platform == 'darwin'",
]

setup(
    name="maestro-music",
    version="1.0.0",
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
    py_modules=["maestro", "mac_presence", "icon", "helpers"],
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
