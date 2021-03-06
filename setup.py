from os import name as sys_name
from setuptools import setup


setup(
    name='maestro',
    version='1.1.2',
    author="Prajwal Vandana",
    url="https://github.com/PrajwalVandana/maestro-cli",
    description="A simple command line tool to play songs (or any audio files, really).",
    keywords="music, sound, audio, music-player, cli",
    py_modules=['maestro'],
    install_requires=['click', 'just_playback', 'getch;platform_system!="Windows"'],
    entry_points={
        'console_scripts': [
            'maestro = maestro:cli',
        ],
    },
)
