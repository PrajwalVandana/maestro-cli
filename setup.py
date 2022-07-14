from os import name as sys_name
from setuptools import setup

dependencies = ['click', 'playsound', 'pygame>=1.9.2']
if sys_name != 'nt':
    dependencies.append('getch')

setup(
    name='maestro',
    author="Prajwal Vandana",
    keyword="music, sound, audio, music-player, cli",
    version='1.0.0',
    py_modules=['maestro'],
    install_requires=dependencies,
    entry_points={
        'console_scripts': [
            'maestro = maestro:cli',
        ],
    },
)
