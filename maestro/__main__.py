import sys

from multiprocessing import freeze_support

from maestro.main import cli


if __name__ == "__main__":
    # check if frozen
    if getattr(sys, "frozen", False):
        freeze_support()

    # click passes ctx, no param needed
    cli()  # pylint: disable=no-value-for-parameter
