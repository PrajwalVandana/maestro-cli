from os import name as sys_name
from setuptools import setup


setup(
    name='maestro',
    version='1.1.6',
    author="Prajwal Vandana",
    url="https://github.com/PrajwalVandana/maestro-cli",
    description="A simple command line tool to play songs (or any audio files, really).",
    keywords="music, sound, audio, music-player, cli",
    py_modules=['maestro'],
    install_requires=['click', 'just_playback', 'getkey', 'tinytag'],
    entry_points={
        'console_scripts': [
            'maestro = maestro:cli',
        ],
    },
)
