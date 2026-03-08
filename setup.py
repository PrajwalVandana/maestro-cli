from os.path import normpath
import re

from setuptools import setup, find_packages


d = {}
with open(normpath("maestro/__version__.py"), encoding="utf-8") as version_file:
    exec(version_file.read(), d)  # pylint: disable=exec-used
VERSION = d["VERSION"]

_INLINE_COMMENT_RE = re.compile(r"\s+#")


def read_requirements(path: str) -> list[str]:
    requirements: list[str] = []
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith(("-r ", "--requirement ")):
                _, included_path = line.split(maxsplit=1)
                requirements.extend(read_requirements(included_path))
                continue

            if line.startswith(("-c ", "--constraint ")):
                continue

            match = _INLINE_COMMENT_RE.search(line)
            if match:
                line = line[: match.start()].rstrip()

            if line:
                requirements.append(line)

    return requirements


install_requires = read_requirements("requirements.txt")


def main() -> None:
    setup(
        name="maestro-music",
        version=VERSION,
        author="Prajwal Vandana",
        url="https://github.com/PrajwalVandana/maestro-cli",
        description="A simple command line tool to play songs (or any audio files, really).",
        long_description=open("readme.md", encoding="utf-8").read(),
        license="MIT",
        license_files=["LICENSE"],
        long_description_content_type="text/markdown",
        keywords=[
            "music",
            "sound",
            "audio",
            "music-player",
            "cli",
            "ogg",
            "vorbis",
            "ogg vorbis",
            "flac",
            "mp3",
            "wav",
            "spotify",
            "youtube",
            "audio-visualization",
            "audio-visualizer",
        ],
        packages=find_packages(include=["maestro"]),
        install_requires=install_requires,
        entry_points={
            "console_scripts": [
                "maestro = maestro.main:cli",
            ],
        },
    )


if __name__ == "__main__":
    main()
