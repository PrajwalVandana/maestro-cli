# Maestro
`maestro` is a command-line tool to play songs (or any audio, really) in the terminal.

## Installation
Download one of the wheels or tarballs or whatnot from the `dist/` folder. Alternatively, you can build `maestro` yourself—download `setup.py` and `maestro.py` into the same EMPTY folder, then run
```
pip install PATH_TO_FOLDER_THAT_HAS_SETUP_AND_MAESTRO
```

### Platforms
Tested on macOS with MP3 and WAV. `maestro` was built to be cross-platform but unfortunately I don't have a Windows or Linux machine to test on.

Should support `.wav`, `.flac`, and `.mp3`.

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
