# maestro
[![PyPI downloads](https://static.pepy.tech/badge/maestro-music)](https://pepy.tech/project/maestro-music) [![PyPI version](https://badge.fury.io/py/maestro-music.svg)](https://badge.fury.io/py/maestro-music) [![Support server](https://img.shields.io/discord/1117677384846544896.svg?color=7289da&label=maestro-cli&logo=discord)](https://discord.gg/AW8fh2QEav)

`maestro` is a command-line tool to play songs (or any audio, really) in the terminal.
![](https://github.com/PrajwalVandana/maestro-cli/raw/master/data/player.png)

Check out the [Discord server](https://discord.gg/AW8fh2QEav)!
## Features
- [cross-platform](#platforms)!
- [add songs](#adding-songs) from YouTube, YouTube Music, or Spotify!
- [stream your music](#streaming)!
- [lyrics](#lyrics)!
    - romanize foreign-language lyrics
    - translate lyrics
- [clips](#clips)!
- filter by [tags](#tags)!
- [listen statistics](#listen-statistics)!
- [shuffle](#shuffling)! (along with precise control over the behavior of shuffling when repeating)
- [audio visualization](#visualization) directly in the terminal!
- [Discord integration](#discord-status)!
- Now Playing Center integration on macOS! (allows headphone controls)
![](https://github.com/PrajwalVandana/maestro-cli/raw/master/data/now_playing.png)
- [music discovery](#music-discovery)!
## Installation
### Using `pip`
Make sure you have Python 3 and `pip` installed.

First, run
```
pip install maestro-music
```
**NOTE**: `pip install maestro` and `pip install maestro` will NOT work, they are totally unrelated PyPI packages.

Now, if you want to be able to directly download songs from YouTube or Spotify, you'll need to install [FFmpeg](https://ffmpeg.org/download.html). You can download FFmpeg yourself globally, or locally with `maestro download-ffmpeg`.
### Download executable
Using Python and `pip` is the preferred way; executables may be slower, have bugs, etc.
#### macOS
Download the `.pkg` file corresponding to your Mac's architecture; Apple Silicon (M1, M2, M3, etc.) or Intel. Right click on the file in Finder and click "Open" (double clicking won't work). The installation may be a bit slow, and the first run of `maestro` will probably be slow as well.
#### Windows
Download and install using `maestro-installer.exe`.
#### Linux
Built on Ubuntu; should work on other Linux distros too. Download and unzip `maestro-ubuntu.tar.gz`. This should unzip a folder named `dist`, which contains a single folder named `maestro`. Inside `maestro` will be another folder, `_internal`, and two scripts: `maestro` and `install-maestro`. Assuming you unzipped inside `Downloads`, run
```bash
cd Downloads/dist/maestro
sudo ./install-maestro
```
You can then safely delete `dist`.
## Known Issues
If you get a segmentation fault when running `maestro play` on macOS, it may be caused by an issue with the Python installation that comes bundled with macOS, as Apple uses an old version of `ncurses` for the `curses` module. To fix this, you can install Python directly from the Python website at python.org/downloads, which should fix the issue.
## Platforms
Tested heavily on macOS, lightly on Windows and (Ubuntu) Linux. `maestro` was coded to be cross-platform, but if there are any problems, please open an issue (or PR if you know how to fix it!). You can also join the [Discord server](https://discord.gg/AW8fh2QEav) and ask for help there.

`maestro` *should* work on any 3.x version of Python, but I coded it on 3.12 and haven't tested it on earlier versions.

Supports `.mp3`, `.wav`, `.flac`, and `.ogg` (Ogg Vorbis).
## Usage
Run `maestro -h` to get a list of commands. Run `maestro <some command> -h` to get comprehensive help for that command—the below is just an overview.

`maestro` uses the concept of a positive integer **song ID** to uniquely refer to each song; any place where `maestro` expects a song ID should also allow a search phrase—if only one song matches, `maestro` will infer the song ID.
### Adding Songs
You can add a song from a file or folder with `maestro add <PATH>`. To add songs in subfolders as well, pass the `-R`/`--recursive` flag.

Pass the `-Y`/`--youtube` flag to download from a YouTube or YouTube Music URL instead of a file path. This requires FFmpeg. Passing a YouTube Music **song** URL (not "Video") is recommended, as passing "Video"s (i.e. just normal YouTube videos) can sometimes mess up the artist/album data (this can always be fixed manually with the `maestro metadata` command, though).

Pass the `-S`/`--spotify` flag to download from a Spotify URL instead of a file path. This also requires installing FFmpeg.

Pass the `-P` or `--playlist` flag to download an entire YouTube playlist from a song URL with a playlist component, e.g. https://www.youtube.com/watch?v=V1Z586zoeeE&list=PLfSdF_HSSu55q-5p-maISZyr19erpZsTo. The `-P` flag is unnecessary if the URL points directly to a playlist, e.g. https://www.youtube.com/playlist?list=PLfSdF_HSSu55q-5p-maISZyr19erpZsTo.

By default, `maestro add` copies the file to its internal database (`~/.maestro-files`), but you can pass the `-M` or `--move` flag to move the file instead. You can also change the folder where the songs are stored with `maestro dir`.
### Tags
Playlists don't exist—`maestro` uses **tags**. For example, let's say you want to be able to listen to all your rap songs together. Instead of adding them all to a playlist, run `maestro tag <space-separated song IDs for each rap song> -t rap`. Then `maestro play rap` will play all the songs you've added the `rap` tag to. Basically, if song `s` has tag `t`, then you can think of song `s` as belonging to the playlist defined by tag `t`. The advantage of tags over playlists is that you can combine tags; `maestro play A B` will play only songs tagged `A` or `B` (add the `-M/--match-all` flag to play only songs tagged `A` *and* `B`).
### Listen Statistics
`maestro` also tracks your listen time—total and by year. You can see this with `maestro list` and/or `maestro entry`. For example, to see your top 10 listened songs this year (by average number of times listened; note that this is NOT the number of times the song was played, but rather the total listen time for that song divided by the duration), run `maestro list --reverse --sort times-listened --top 10 --year cur`—replace 'cur' with e.g. '2020' to get the listen times for 2020 instead.
![](https://github.com/PrajwalVandana/maestro-cli/raw/master/data/list.png)
### Clips
Ever been listening to music, and you're skipping every song because you keep getting bored of them? You like the songs, you're just not in the mood to listen to all of them entirely.

Introducing clips, something I've always wished the big companies like Spotify and YouTube Music would do. Use `maestro clip <song ID> <START> <END>` to define a clip for any song with a start and end timestamp (or use the clip editor for fine-grained control with `maestro clip <song ID>`), then `maestro play -C` to play in "clip mode" (can also be toggled in the player session with the `c` key)—this will play the clips for each song (or the entire song if there's no clip). Now you can listen to only the best parts of your music!

By default, `maestro clip` creates a clip named 'default'; you can add additional clips with the `--name` option:
```bash
maestro clip <song ID> --name clip1
maestro set-clip <song ID> clip1
```
The `maestro set-clip` command will set 'clip1' as the clip to be played in clip mode instead of 'default'.
### Lyrics
`maestro add` will automatically attempt to download lyrics (synced if possible) for the song. You can romanize foreign-language lyrics with `maestro translit <song ID> --save`, which will save the romanization as an override `.lrc` file (the original lyrics will still be preserved in the metadata of the song's file, but the override will be shown). You can add a translation for a song with `maestro translate <song ID> --save`, which can then be shown with the lyrics using `maestro play --lyrics --translated-lyrics`. Not passing `--save` to either command will print the output instead of saving it.

Press `y` in the player session to toggle lyrics, `t` to toggle translated lyrics. To scroll through lyrics, change focus to the lyrics window with `}` (you can change focus back to the queue with `{`).
### Shuffling
`maestro play` accepts two shuffle options, `-s`/`--shuffle` and `-r`/`--reshuffle`. The first is for shuffling the song before the player session starts, and the second is for reshuffling the queue when it loops (the `-r` option is ignored if you don't also pass the `-L`/`--loop` flag to loop the queue). The default for both is `0`, i.e. no shuffling. To shuffle completely randomly, pass `-1` to either option; otherwise, passing any positive integer `n` will ensure that each song is no more than `n` positions away in the queue from its previous position.
### Visualization
Run `maestro play --visualize` or click `v` in the player session to show the visualizer.
### Discord Status
Run `maestro play --discord` or click `d` in the player session to show the currently playing song in your Discord status (requires the Discord app to be open). Hovering over the image will show the album name. To show album art, requires signing up/logging in with `maestro signup`/`maestro login`.

<img src="https://github.com/PrajwalVandana/maestro-cli/raw/master/data/discord.png" width="300"/>

### Streaming
If you're logged in as `user123`, run `maestro play --stream` (or click `s` in the player session) to stream your music to `maestro-music.vercel.app/listen-along/user123`. This will show up as a "Listen Along" button on your Discord status too, if the Discord status is enabled (some versions of the Discord app don't show buttons on your own status, but it should show for everyone else).
![](https://github.com/PrajwalVandana/maestro-cli/raw/master/data/stream.png)
### Music Discovery
Use `maestro recommend <song ID>` to recommend similar songs (searches up the song name on YouTube Music).