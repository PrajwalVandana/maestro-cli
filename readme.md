# maestro
`maestro` is a command-line tool to play songs (or any audio, really) in the terminal.

## Installation
Download the wheel or tarball (wheel is usually better) from the `dist/` folder, then run
```
pip install PATH_TO_WHEEL
```
Alternatively, you can build `maestro` yourself—download `setup.py` and `maestro.py` into the same EMPTY folder, then run
```
pip install PATH_TO_FOLDER_THAT_HAS_SETUP_AND_MAESTRO
```
OR
```
python PATH_TO_SETUP_PY install
```

**NOTE**: `pip install maestro` will NOT work, this downloads a totally unrelated package from PyPI.

### Known Installation Issues

`maestro` uses [just_playback](https://github.com/cheofusi/just_playback) to play sound, which uses a C library called [miniaudio](https://github.com/mackron/miniaudio). Unfortunately, the creators did not provide wheels, so installation of `just_playback` and therefore `maestro` usually fails if there's any problems with your C/C++ compiler. Here are platforms where there are known issues:

#### M1 Macs

There's a problem with the flag `-march=native` for older versions of the `clang` compiler. I manually removed this from the `just_playback` code and built a M1-compatible version. Just check out the `dependency_builds/` folder in this repo, and look for the wheel that says `arm64`. Then, run
```
pip install PATH_TO_DOWNLOADED_ARM64_WHEEL
```
and *now* installing `maestro` should work.

#### Windows

If you get this error on a 64-bit Windows
```
error: Microsoft Visual C++ 14.0 or greater is required. Get it with "Microsoft C++ Build Tools": https://visualstudio.microsoft.com/visual-cpp-build-tools/
```
find the `win_amd64` wheel of `just_playback` in `dependency_builds`, then run
```
pip install PATH_TO_DOWNLOADED_WHEEL
```
and *now* installing `maestro` should work. Another option (especially if you're on a 32-bit Windows) is to just get C++ Build Tools.

## Platforms
Tested on macOS and Windows. `maestro` was built to work on Linux as well but unfortunately I don't have a Linux machine to test on.

Supports `.mp3`, `.wav`, `.flac`, and `.ogg`.

## Usage
For the most part, `maestro` is pretty self-explanatory and easy to use—running `maestro` or `maestro -h` gives you an overview of the commands, and `maestro [command] -h` for any one specific command is hopefully self-explanatory enough.

`maestro` allows you to add and remove songs with `maestro add` and `maestro remove`, add tags to songs with `maestro add-tags` and `maestro remove-tags`, rename songs with `maestro rename`, etc.

`maestro play` is very versatile, allowing you to shuffle your playlist, reverse your playlist (most recently added first), play only a single song, or play only songs with certain tags.

Every song is given a positive integer ID (this does *not* necessarily equal its position in your playlist)—so if you want to remove the song `examplesong`, you would run
```
maestro search examplesong
```
which would show you all songs that contained the phrase `examplesong` along with their ID and tag(s). Let's say the ID was 17, you would then run
```
maestro remove 17
```

If you wanted to search for all MP3 files (for whatever reason), this works:
```
maestro search .mp3
```

## Other Tips

### Downloading Songs
Use [youtube-dl](https://github.com/ytdl-org/youtube-dl) to download from YouTube, like this:
```
youtube-dl -x --audio-format WHATEVER_FORMAT LINK_TO_VIDEO_OR_PLAYLIST
```
`-x` will download only the audio instead of the entire video

## Thanks

Big thanks to the creators of [just_playback](https://github.com/cheofusi/just_playback), no doubt the best Python module for playing sound!
