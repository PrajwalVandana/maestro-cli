# Maestro
`maestro` is a command-line tool to play songs (or any audio, really) in the terminal.

## Installation
Download one of the wheels or tarballs or whatnot from the `dist/` folder. Alternatively, you can build `maestro` yourself—download `setup.py` and `maestro.py` into the same folder (preferably an empty one so you can easily clean it up later), then run
```
python setup.py install
```

### Platforms
Only allows `.mp3`, unfortunately 😔

Tested on macOS. `maestro` was built to be cross-platform but unfortunately I don't have a Windows or Linux machine to test on.

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

A feature to refer to songs with a phrase instead of having to know the ID of the song is coming soon!

## Other Tips

### Downloading MP3 Songs
Use [youtube-dl](https://github.com/ytdl-org/youtube-dl) to download as MP3 from YouTube, like this:
```
youtube-dl -x --audio-format mp3 LINK_TO_VIDEO_OR_PLAYLIST
```
`-x` will download only the audio instead of the entire video

### Converting Songs to MP3
There's a bunch of online conversion tools, and if you want something more versatile there's [ffmpeg](https://ffmpeg.org/).

#### macOS
```
brew install ffmpeg
```
#### Linux
```
apt-get install ffmpeg libavcodec-extra
```
#### Windows
Check out [this wikiHow link](https://www.wikihow.com/Install-FFmpeg-on-Windows).