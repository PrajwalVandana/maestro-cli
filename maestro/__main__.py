import sys

from multiprocessing import freeze_support

from maestro.maestro import cli


if __name__ == "__main__":
    # check if frozen
    if getattr(sys, "frozen", False):
        freeze_support()
    cli()
