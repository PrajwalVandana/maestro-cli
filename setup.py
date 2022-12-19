from setuptools import setup


setup(
    name="maestro",
    version="1.0.0",
    author="Prajwal Vandana",
    url="https://github.com/PrajwalVandana/maestro-cli",
    description="A simple command line tool to play songs (or any audio files, really).",
    keywords="music, sound, audio, music-player, cli",
    py_modules=["maestro", "mac_presence"],
    install_requires=[
        "click",
        "just_playback",
        "tinytag",
        "windows-curses; sys_platform == 'win32'",
        "pyobjc-core; sys_platform == 'darwin'",
        # "pyobjc-framework-ApplicationServices; sys_platform == 'darwin'",
        # "pyobjc-framework-AVFoundation; sys_platform == 'darwin'",
        "pyobjc-framework-Cocoa; sys_platform == 'darwin'",
        # "pyobjc-framework-CoreAudio; sys_platform == 'darwin'",
        # "pyobjc-framework-CoreMedia; sys_platform == 'darwin'",
        "pyobjc-framework-MediaPlayer; sys_platform == 'darwin'",
        # "pyobjc-framework-Quartz; sys_platform == 'darwin'"
    ],
    extras_require={
        "discord": ["pypresence"],
    },
    entry_points={
        "console_scripts": [
            "maestro = maestro:cli",
        ],
    },
    include_package_data=True
)
