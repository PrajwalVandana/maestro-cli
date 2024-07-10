import os

from datetime import date
from urllib.parse import urljoin


# region constants

DISCORD_ID = 1039038199881810040

CUR_YEAR = date.today().year
EXTS = (".mp3", ".wav", ".flac", ".ogg")
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

# region paths
MAESTRO_DIR = os.path.join(os.path.expanduser("~"), ".maestro-files/")

SETTINGS_FILE = os.path.join(MAESTRO_DIR, "settings.json")
LOGFILE = os.path.join(MAESTRO_DIR, "maestro.log")
DEFAULT_SETTINGS = {
    "song_directory": os.path.join(MAESTRO_DIR, "songs/"),
    "last_version_sync": 0,
    # "data_outlets": {
    #     "file": [],
    #     "serial": [],
    # },
}
SETTINGS = {}

SONGS_INFO_PATH = os.path.join(MAESTRO_DIR, "songs.txt")

STATS_DIR = os.path.join(MAESTRO_DIR, "stats/")
CUR_YEAR_STATS_PATH = os.path.join(STATS_DIR, f"{CUR_YEAR}.txt")
TOTAL_STATS_PATH = os.path.join(STATS_DIR, "total.txt")
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
VOLUME_STEP = 0.01  # self.volume is 0-1
MIN_PROGRESS_BAR_WIDTH = 20
MIN_VOLUME_BAR_WIDTH, MAX_VOLUME_BAR_WIDTH = 10, 40
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

ICECAST_SERVER = "maestro-icecast.eastus2.cloudapp.azure.com"  # Azure-hosted Icecast server

MAESTRO_SITE = "https://maestro-music.vercel.app"
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