from os import name as sys_name
from setuptools import setup


setup(
    name='maestro',
    author="Prajwal Vandana",
    keyword="music, sound, audio, music-player, cli",
    version='1.1.2',
    py_modules=['maestro'],
    install_requires=['click', 'just_playback', 'getch;platform_system=="Linux"'],
    entry_points={
        'console_scripts': [
            'maestro = maestro:cli',
        ],
    },
)
