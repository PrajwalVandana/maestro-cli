import warnings

import numpy as np

from maestro import config
from maestro.config import print_to_logfile

try:
    from numba import jit
except:  # pylint: disable=bare-except
    jit = lambda x: x
    print_to_logfile("Numba not installed. Visualization will be slower.")
try:
    from numba.core.errors import NumbaWarning

    warnings.simplefilter("ignore", category=NumbaWarning)
except:  # pylint: disable=bare-except
    pass


@jit
def lerp(start, stop, t):
    return start + t * (stop - start)


@jit(forceobj=True)
def bin_average(arr: np.ndarray, n, include_remainder=False, func=None):
    if func is None:
        func = np.max

    remainder = arr.shape[1] % n
    if remainder == 0:
        return func(arr.reshape(arr.shape[0], -1, n), axis=1)

    avg_head = func(arr[:, :-remainder].reshape(arr.shape[0], -1, n), axis=1)
    if include_remainder:
        avg_tail = func(
            arr[:, -remainder:].reshape(arr.shape[0], -1, remainder), axis=1
        )
        return np.concatenate((avg_head, avg_tail), axis=1)

    return avg_head


@jit(forceobj=True)
def render(
    num_bins,
    freqs: np.ndarray,
    frame,
    visualizer_height,
    mono=None,
    include_remainder=None,
    func=None,
):
    """
    mono:
        True:  forces one-channel visualization
        False: forces two-channel visualization
        None:  if freqs[0] == freqs[1], one-channel, else two
    """
    if func is None:
        func = np.max

    if mono is None:
        mono = np.array_equal(freqs[0], freqs[1])

    if not mono:
        gap_bins = 1 if num_bins % 2 else 2
        num_bins = (num_bins - 1) // 2
    else:
        gap_bins = 0
        freqs[0, :, frame] = (freqs[0, :, frame] + freqs[1, :, frame]) / 2

    num_vertical_block_sizes = len(config.VERTICAL_BLOCKS) - 1
    freqs = np.round(
        bin_average(
            freqs[:, :, frame],
            num_bins,
            (
                (freqs.shape[-2] % num_bins) > num_bins / 2
                if include_remainder is None
                else include_remainder
            ),
            func=func,
        )
        / 80
        * visualizer_height
        * num_vertical_block_sizes
    )

    arr = np.zeros((int(not mono) + 1, visualizer_height, num_bins))
    for b in range(num_bins):
        bin_height = freqs[0, b]
        h = 0
        while bin_height > num_vertical_block_sizes:
            arr[0, h, b] = num_vertical_block_sizes
            bin_height -= num_vertical_block_sizes
            h += 1
        arr[0, h, b] = bin_height
        if not mono:
            bin_height = freqs[1, b]
            h = 0
            while bin_height > num_vertical_block_sizes:
                arr[1, h, b] = num_vertical_block_sizes
                bin_height -= num_vertical_block_sizes
                h += 1
            arr[1, h, b] = bin_height

    res = []
    for h in range(visualizer_height - 1, -1, -1):
        s = ""
        for b in range(num_bins):
            if mono:
                s += config.VERTICAL_BLOCKS[arr[0, h, b]]
            else:
                s += config.VERTICAL_BLOCKS[arr[0, h, num_bins - b - 1]]
        if not mono:
            s += " " * gap_bins
            for b in range(num_bins):
                s += config.VERTICAL_BLOCKS[arr[1, h, b]]
        res.append(s)

    return res