from os import name as sys_name
from setuptools import setup

dependencies = ['click', 'playsound', 'pygame']
if sys_name != 'nt':
    dependencies.append('getch')

setup(
    name='maestro',
    version='0.1.0',
    py_modules=['maestro'],
    install_requires=dependencies,
    entry_points={
        'console_scripts': [
            'maestro = maestro:cli',
        ],
    },
)
