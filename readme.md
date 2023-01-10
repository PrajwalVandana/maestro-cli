# maestro
`maestro` is a command-line tool to play songs (or any audio, really) in the terminal.

## Features

- cross-platform!
- audio visualization directly in the terminal!
- Discord integration!
- [clips!](#maestro-clip)
- shuffle! (along with precise control over the behavior of shuffling when looping)
- filter by [tags](#usage)!

## Installation

Make sure you have Python 3 and `pip` installed.

First, run
```
pip install maestro-music
```

Now, if you want to be able to directly download songs from YouTube, you'll need to install [FFmpeg](https://github.com/FFmpeg/FFmpeg).

### Installing FFmpeg

**EASIEST**: `conda install -c conda-forge ffmpeg`

But if you don't want to get `conda`, here are the instructions for each platform:

#### macOS
Requires [Homebrew](https://brew.sh/):
```
brew install ffmpeg
```

#### Windows

Just check out the [FFmpeg website](https://ffmpeg.org/download.html) and download the latest version of the Windows build. Make sure to add the `bin` folder to your PATH.

Here are some instructions:
[https://www.geeksforgeeks.org/how-to-install-ffmpeg-on-windows/](https://www.geeksforgeeks.org/how-to-install-ffmpeg-on-windows/)

#### Linux
```
sudo apt install ffmpeg
```

**NOTE**: `pip install maestro` will NOT work, this downloads a totally unrelated package from PyPI.

### Known Installation Issues

Before trying the below, make sure you have the latest version of `pip` installed:
```
pip install --upgrade pip
```

Also, if you have `conda`, see if running the following fixes your issue before trying anything below:
```
conda install libsndfile ffmpeg cffi
```

`maestro` uses [just_playback](https://github.com/cheofusi/just_playback) to play sound, which uses a C library called [miniaudio](https://github.com/mackron/miniaudio). Unfortunately, the creators did not provide wheels, so installation of `just_playback` and therefore `maestro` usually fails if there's any (compatibility or otherwise) problems with your C/C++ compiler. Here are platforms where there are known issues:

#### M1 Macs

There's a problem with the flag `-march=native` for older versions of the `clang` compiler. I manually removed this from the `just_playback` code and built a M1-compatible version. Just check out the `dependency_builds/` folder in this repo, and look for the wheel that says `arm64`. Download it, then run
```
pip install PATH_TO_DOWNLOADED_ARM64_WHEEL
```
and *now* installing `maestro` should work.

#### Windows

If you get this error on a 64-bit Windows
```
error: Microsoft Visual C++ 14.0 or greater is required. Get it with "Microsoft C++ Build Tools": https://visualstudio.microsoft.com/visual-cpp-build-tools/
```
find and download the `win_amd64` wheel of `just_playback` in `dependency_builds`, then run
```
pip install PATH_TO_DOWNLOADED_WIN64_WHEEL
```
and *now* installing `maestro` should work. Another option (especially if you're on a 32-bit Windows) is to just get Visual C++ Build Tools.

#### Linux

If you have issues, try:
 * upgrading pip: `pip install --upgrade pip`
 * uninstalling `just_playback`: `pip uninstall just_playback`
 * reinstalling `just_playback` with the `--no-binary` flag: `pip install just_playback --no-binary just_playback --force-reinstall --upgrade`

Check this out: [https://github.com/cheofusi/just_playback/issues/21](https://github.com/cheofusi/just_playback/issues/21) ... and good luck 💀.

## Platforms

Tested heavily on macOS Monterey, barely at all on Windows and Linux. `maestro` was coded to be cross-platform, but if there are any problems, please open an issue (or PR if you know how to fix it!).

Supports `.mp3`, `.wav`, `.flac`, and `.ogg`.

## Usage

Run `maestro -h` to get a list of commands. Run `maestro <some command> -h` to get comprehensive help for that command—the below is just an overview.

`maestro` uses the concept of a positive integer **song ID** to uniquely refer to each song.

Also, playlists don't exist—`maestro` uses **tags**. For example, let's say you want to be able to listen to all your Jon Bellion songs together. Instead of adding them all to a playlist, run `maestro -t jon-bellion <song IDs for each Jon Bellion song>`. Then `maestro play jon-bellion`. If song `s` has tag `t`, then you can think of song `s` as belonging to the playlist defined by tag `t`.

`maestro` also tracks listen time—total and by year. You can see this with `maestro list` and/or `maestro entry`. To get the details for this year, run `maestro entry -y cur`—replace 'cur' with e.g. '2020' to get the listen times for 2020 instead.

### `maestro add`

Add a song (can be a folder of songs too!) given a file path.

Pass the `-u` or `--url` flag to download from a YouTube or YouTube Music URL instead of a file path. This requires installing [FFmpeg](https://github.com/FFmpeg/FFmpeg).

Pass the `-p` or `--playlist` flag to download an entire YT playlist from a song URL with a playlist component, e.g. https://www.youtube.com/watch?v=V1Z586zoeeE&list=PLfSdF_HSSu55q-5p-maISZyr19erpZsTo. The `-p` flag is unnecessary if the URL points directly to a playlist, e.g. https://www.youtube.com/playlist?list=PLfSdF_HSSu55q-5p-maISZyr19erpZsTo.

By default, `maestro add` copies the file to its internal database (`~/.maestro-files`), but you can pass the `-m` or `--move` flag to move the file instead.

### `maestro cache`
Calculate (or recalculate with the `-r/--recache` flag) visualization frequency data (see [`maestro play`](#maestro-play)) for songs passed by ID (or all songs with the `-a/--all` flag.

If you ever go into the song database (located at `~/.maestro-files`) and manually edit a song, e.g. trimming (not recommended but should be fine as long as you don't mess with the name of the file), you should run `maestro cache --recache <SONG_ID>` to readjust the visualization.

### `maestro clip`

Ever been listening to music, and you're skipping every song because you keep getting bored of them? You like the songs, you're just not in the mood to listen to all of them entirely.

Introducing clips, something I've always wished the big companies like Spotify, YT Music would do. Use `maestro clip` to define a clip for any song with a start and end timestamp, then `maestro play -c` to play in "clip mode" (can also be toggled while playing a normal mode session with the `c` key)—this will play the clips for each song (or the entire song if there's no clip). Now you can listen to only the best parts of your music!

### `maestro entry`

List details for a specific song.

### `maestro list`

List songs (or tags) and details. Use `maestro list -h` to see full options (e.g. sort, list only songs with a certain tag, etc.).

### `maestro play`

Play songs. Use `maestro play -h` to see full options. Has lots of features:
- pass tag(s) as arguments to play songs with any of those tag(s) (or songs with all of those tag(s) if you pass the `-m` or `--match-all` flag)
- shuffle playlist with the `-s` or `--shuffle` flag
- play songs in reverse order with the `-r` or `--reverse` flag
- loop playlist with the `-l` or `--loop` flag
- shuffle playlist on loop with the `-r` or `--reshuffle` flag
- show an audio visualization with the `-V` or `--visualize` flag
  - you may notice some wait time for the visualization to properly load the first time a song is visualized (~7 seconds), but after that the visualization is cached and should load quickly
- works with headphone buttons (and the Touch Bar and Siri!) on Mac using the Now Playing Center!
- works with Discord status! (pass the `-d` or `--discord` flag)

While playing:
- like a song and want to play *that specific song* on loop? click `l` while playing to toggle loop mode (not the same as passing `-l` to `maestro play`!)
- seek with left/right arrow keys
- volume up/down with `[` and `]`
- remove selected song (not necessarily the currently playing song) from current playlist with `d`
- scroll with mouse or up/down arrow keys to scroll the selected song
- `c` to toggle clip mode
- `v` to toggle visualization mode
- `m` to mute
- `r` to replay a song
- `a` to add a song by ID to the end of the playlist
- `b` or `p` to go back to the previous song
- `s` or `n` to go to the next song
- space to pause/play
- `e` to end after the current song
- `q` to end immediately (don't just close the window or `CTRL-c`, this messes up the accuracy of the listen time statistics)

### `maestro push`

Push a song to the top (or bottom) of your song list. Useful if you usually play the most recently added songs first (`maestro play -r`), for example—you can use `maestro push` to push a song to the top of your list so it's the first song to play.

### `maestro recommend` (experimental)

Recommend songs similar to a song title (specified directly or by ID) using YouTube Music. Equivalent to searching for the title of the song on YouTube Music, clicking on the first "Song" result, and then looking at the "Up Next" section.

### `maestro remove`

Remove a song (or tag).

### `maestro rename`

Rename a song (or tag).

### `maestro search`

Search for songs (or tags) by name.

### `maestro tag`

Add tags to a song, e.g. `maestro tag -t harry-styles 87` (adds the tag 'harry-styles' to the song with ID 87).

### `maestro unclip`

Remove a clip from a song, e.g. `maestro unclip 87` (removes the clip from the song with ID 87).

### `maestro untag`

Remove tags from a song, e.g. `maestro untag -t harry-styles 87` (removes the tag 'harry-styles' from the song with ID 87).

## Thanks

Big thanks to the creators of [just_playback](https://github.com/cheofusi/just_playback), no doubt the best Python module for playing sound!
