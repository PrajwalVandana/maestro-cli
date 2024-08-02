import os

from datetime import date, datetime
from urllib.parse import urljoin


# region constants

DISCORD_ID = 1039038199881810040

PROMPT_MODES = {
    "insert": 0,
    "add": 1,
    "tag": 2,
}
LOOP_MODES = {
    "none": 0,
    "one": 1,
    "inf": 2,
}

EXTS = (".mp3", ".wav", ".flac", ".ogg")
METADATA_KEYS = (
    "album",
    "albumartist",
    "artist",
    "artwork",
    "comment",
    "compilation",
    "composer",
    "discnumber",
    "genre",
    "lyrics",
    "totaldiscs",
    "totaltracks",
    "tracknumber",
    "tracktitle",
    "year",
    "isrc",
    "#bitrate",
    "#codec",
    "#length",
    "#channels",
    "#bitspersample",
    "#samplerate",
)
INDIC_SCRIPTS = (
    "bengali",
    "assamese",
    "modi",
    "malayalam",
    "devanagari",
    "sinhala",
    "tibetan",
    "gurmukhi",
    "tamil",
    "balinese",
    "thai",
    "burmese",
    "telugu",
    "kannada",
    "gujarati",
    "urdu",
    "lao",
    "javanese",
    "manipuri",
    "oriya",
    "khmer",
)

CUR_YEAR = date.today().year


# region paths
MAESTRO_DIR = os.path.join(os.path.expanduser("~"), ".maestro-files/")

SETTINGS_FILE = os.path.join(MAESTRO_DIR, "settings.json")
LOGFILE = os.path.join(MAESTRO_DIR, "maestro.log")
OLD_LOG_DIR = os.path.join(MAESTRO_DIR, "old-logs/")
DEFAULT_SETTINGS = {
    "song_directory": os.path.join(MAESTRO_DIR, "songs/"),
    "last_version_sync": 0,
}

OLD_SONGS_INFO_PATH = os.path.join(MAESTRO_DIR, "songs.txt")
SONGS_INFO_PATH = os.path.join(MAESTRO_DIR, "songs.json")
OLD_STATS_DIR = os.path.join(MAESTRO_DIR, "stats/")
OVERRIDE_LYRICS_DIR = os.path.join(MAESTRO_DIR, "override-lyrics/")
# endregion

# region player
HORIZONTAL_BLOCKS = {
    1: "▏",
    2: "▎",
    3: "▍",
    4: "▌",
    5: "▋",
    6: "▊",
    7: "▉",
    8: "█",
}
SCRUB_TIME = 5  # in seconds
VOLUME_STEP = 1
MIN_PROGRESS_BAR_WIDTH = 20
MIN_VOLUME_BAR_WIDTH, MAX_VOLUME_BAR_WIDTH = 10, 40

_FARTHEST_RIGHT_CONTROL_DESC = 5
INDENT_CONTROL_DESC = 0
PLAY_CONTROLS = [
    ("SPACE", "pause/play"),
    ("b", "go back to previous song"),
    ("r", "replay song"),
    ("n", "skip to next song"),
    (
        "l",
        "loop the current song once ('l' in status bar). press again to loop infinitely ('L' in status bar). press once again to turn off looping",
    ),
    ("c", "toggle clip mode"),
    ("v", "toggle visualization"),
    ("LEFT", "rewind 5s"),
    ("RIGHT", "fast forward 5s"),
    ("[", "decrease volume"),
    ("]", "increase volume"),
    ("m", "mute/unmute"),
    (
        "e",
        "end the song player after the current song finishes (indicator in status bar, 'e' to cancel)",
    ),
    ("q", "quit the song player immediately"),
    (
        "UP/DOWN",
        "to scroll through the queue (mouse scrolling should also work)",
    ),
    ("p", "snap back to the currently playing song"),
    (
        "g",
        "go to the next page/loop of the queue (ignored if not repeating queue)",
    ),
    (
        "BACKSPACE/DELETE",
        "delete the selected (not necessarily currently playing!) song from the queue",
    ),
    ("d", "toggle Discord rich presence"),
    (
        "a",
        "add a song to the end of the queue. Opens a prompt to enter the song name or ID: ENTER to confirm, ESC to cancel.",
    ),
    (
        "i",
        "insert a song in the queue after the selected song. Opens a prompt like 'a'.",
    ),
    ("t", "add a tag to all songs in the queue. Opens a prompt like 'a'."),
    (
        "s",
        "toggle stream (streams to maestro-music.vercel.app/listen/[USERNAME]), requires login",
    ),
    ("y", "toggle lyrics"),
    (
        "o",
        "reload song data (useful if you've changed e.g lyrics, tags, or metadata while playing)",
    ),
    ("?", "toggle this help message"),
]
for key, desc in PLAY_CONTROLS:
    if INDENT_CONTROL_DESC < len(key) <= _FARTHEST_RIGHT_CONTROL_DESC:
        INDENT_CONTROL_DESC = len(key)
# endregion

# region visualizer
FPS = 60

STEP_SIZE = 512  # librosa default
VIS_SAMPLE_RATE = STEP_SIZE * FPS

VERTICAL_BLOCKS = {
    0: " ",
    1: "▁",
    2: "▂",
    3: "▃",
    4: "▄",
    5: "▅",
    6: "▆",
    7: "▇",
    8: "█",
}
VISUALIZER_HEIGHT = 8  # should divide 80
WAVEFORM_HEIGHT = 6  # should also divide 80

VIS_FLATTEN_FACTOR = 3  # higher = more flattening; 1 = no flattening
WAVEFORM_FLATTEN_FACTOR = 20
# endregion

# region stream
STREAM_SAMPLE_RATE = 44100
STREAM_CHUNK_SIZE = 256

ICECAST_SERVER = (
    "maestro-icecast.eastus2.cloudapp.azure.com"  # Azure-hosted Icecast server
)

MAESTRO_SITE = "https://maestro-music.vercel.app"
IMAGE_URL = f"{MAESTRO_SITE}/api/get_artwork/"
# endregion

# region auth
AUTH_SERVER = f"{MAESTRO_SITE}/api/"
# AUTH_SERVER = "http://localhost:5001/api/"  # DEBUG
USER_EXISTS_URL = urljoin(AUTH_SERVER, "user_exists")
SIGNUP_URL = urljoin(AUTH_SERVER, "signup")
LOGIN_URL = urljoin(AUTH_SERVER, "login")
UPDATE_METADATA_URL = urljoin(AUTH_SERVER, "update_metadata")
UPDATE_ARTWORK_URL = urljoin(AUTH_SERVER, "update_artwork")
UPDATE_TIMESTAMP_URL = urljoin(AUTH_SERVER, "update_timestamp")
# endregion

# endregion


settings = {}


def print_to_logfile(*args, **kwargs):
    if "file" in kwargs:
        raise ValueError("file kwargs not allowed for 'print_to_logfile'")
    print(
        datetime.now().strftime("[%Y-%m-%d %H:%M:%S]"),
        *args,
        **kwargs,
        file=open(LOGFILE, "a", encoding="utf-8"),
    )
