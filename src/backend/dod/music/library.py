"""The songs: which are on the list (songs.txt), which are downloaded (tech-spec
5.2; plan step 8).

    library = Library.from_file(SONGS_FILE, settings.cache_dir)
    library.infos()          the list for `welcome` and /api/songs
    library.video("dQw4…")   the file, only for a listed and downloaded id
    library.show("dQw4…")    its light show's picture (timeline.py), if it is current

A download is two files in the cache: `<id>.mp4` and `<id>.json` (title and
length, written by download.py after the video). A song counts as downloaded
when both are there, so a half-finished download never does.

An id is never used to build a path before it is checked against the list
(backend.md 9): /media/<id>.mp4 asks `video()`, which looks it up first.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dod.api.messages import SongInfo

SONGS_FILE = Path(__file__).with_name("songs.txt")
SONG_ID = re.compile(r"[A-Za-z0-9_-]{11}")
MAX_TITLE = 40  # characters on a phone's song button


class SongListError(ValueError):
    """songs.txt has lines that aren't a song. `problems` has one line each."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("bad song list:\n" + "\n".join(f"  {p}" for p in problems))


@dataclass(frozen=True)
class Song:
    id: str
    title: str

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


def youtube_id(link: str) -> str | None:
    """The id from https://www.youtube.com/watch?v=…, https://youtu.be/… or
    https://www.youtube.com/shorts/…; None for anything else."""
    parts = urlsplit(link)
    host = (parts.hostname or "").removeprefix("www.").removeprefix("m.").removeprefix("music.")
    if parts.scheme not in ("http", "https"):
        return None
    if host == "youtube.com" and parts.path == "/watch":
        candidate = parse_qs(parts.query).get("v", [""])[0]
    elif host == "youtube.com" and parts.path.startswith("/shorts/"):
        candidate = parts.path.removeprefix("/shorts/").strip("/")
    elif host == "youtu.be":
        candidate = parts.path.strip("/")
    else:
        return None
    return candidate if SONG_ID.fullmatch(candidate) else None


def parse(text: str) -> list[Song]:
    """songs.txt: one link per line and a short title after it; `#` comments and
    blank lines are left out. Every bad line is named at once."""
    songs: list[Song] = []
    problems: list[str] = []
    seen: dict[str, int] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        link, _, title = line.partition(" ")
        title = title.strip()
        song_id = youtube_id(link)
        if song_id is None:
            problems.append(f"line {number}: not a YouTube link: {link!r}")
            continue
        if not title:
            problems.append(f"line {number}: a short title after the link, please (YouTube's are too long)")
            continue
        if len(title) > MAX_TITLE:
            problems.append(f"line {number}: the title is {len(title)} characters, at most {MAX_TITLE} fit on a phone")
            continue
        if song_id in seen:
            problems.append(f"line {number}: {song_id} is on the list already (line {seen[song_id]})")
            continue
        seen[song_id] = number
        songs.append(Song(id=song_id, title=title))
    if problems:
        raise SongListError(problems)
    return songs


class Library:
    def __init__(self, songs: list[Song], cache_dir: Path) -> None:
        self.songs = list(songs)
        self.cache_dir = cache_dir
        self._by_id = {s.id: s for s in self.songs}

    @classmethod
    def from_file(cls, path: Path, cache_dir: Path) -> Library:
        return cls(parse(path.read_text(encoding="utf-8")), cache_dir)

    def song(self, song_id: str) -> Song | None:
        """The listed song with this id; None for anything else (never touches the disk)."""
        return self._by_id.get(song_id) if isinstance(song_id, str) else None

    def _files(self, song: Song) -> tuple[Path, Path]:
        return self.cache_dir / f"{song.id}.mp4", self.cache_dir / f"{song.id}.json"

    def meta(self, song_id: str) -> dict[str, object] | None:
        """What download.py wrote next to the video, if both files are there."""
        song = self.song(song_id)
        if song is None:
            return None
        video, meta = self._files(song)
        if not (video.is_file() and meta.is_file()):
            return None
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def length(self, song_id: str) -> float | None:
        meta = self.meta(song_id)
        length = meta.get("length") if meta is not None else None
        return float(length) if isinstance(length, (int, float)) and length > 0 else None

    def ready(self, song_id: str) -> bool:
        """Downloaded, with a known length: the main screen can play it."""
        return self.length(song_id) is not None

    def video(self, song_id: str) -> Path | None:
        """The .mp4 of a listed, downloaded song; None for anything else."""
        song = self.song(song_id)
        return self._files(song)[0] if song is not None and self.ready(song_id) else None

    def show(self, song_id: str) -> Path | None:
        """The light show's picture of a listed, downloaded song (timeline.py), if it
        was made by this version of the show; None for anything else."""
        from dod.music import timeline  # here: numpy only when a picture is asked for

        song = self.song(song_id)
        if song is None or not self.ready(song_id) or not timeline.current(self.cache_dir, song.id):
            return None
        return timeline.files(self.cache_dir, song.id)[0]

    def missing(self) -> list[Song]:
        return [s for s in self.songs if not self.ready(s.id)]

    def infos(self) -> list[SongInfo]:
        """For `welcome` and /api/songs, in the list's order."""
        return [SongInfo(id=s.id, title=s.title, length=self.length(s.id), ready=self.ready(s.id)) for s in self.songs]
