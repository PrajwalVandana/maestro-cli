# Maestro
`maestro` is a command-line tool to play songs (or any audio, really) in the terminal.

## Installation
Download one of the wheels or tarballs or whatnot from the `dist/` folder. Alternatively, you can build `maestro` yourself—download `setup.py` and `maestro.py` into the same folder, then run
```
python setup.py install
```

### Platforms
Tested with `.wav` and `.mp3` files on macOS. `maestro` was built to be cross-platform but unfortunately I don't have a Windows to test on.

## Usage
For the most part, `maestro` is pretty self-explanatory and easy to use—running `maestro` or `maestro -h` gives you an overview of the commands, and `maestro [command] -h` for any one specific command is hopefully self-explanatory enough.

`maestro` allows you to add and remove songs with `maestro add` and `maestro remove`, add tags to songs with `maestro add-tags` and `maestro remove-tags`, etc.

`maestro play` is very versatile, allowing you to shuffle your playlist, reverse your playlist (most recently added first), play only a single song, or play only songs with certain tags.

Every song is given an ID—so if you want to remove the song `examplesong` (let's say you forgot whether it was a `.wav` or `.mp3`), you would run `maestro search examplesong`, which would show you all songs that contained the phrase `examplesong` along with their ID and tag(s). Let's say the ID was 17, you would then run `maestro remove 17`.
