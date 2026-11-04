"""Downloads the songs missing from the cache: `./dod songs` (tech-spec 5.2;
plan step 8).

    ./dod songs                every song on the list that isn't downloaded yet
    ./dod songs dQw4w9WgXcQ …  only these (they must be on the list)

Each song: H.264 video with AAC audio in an .mp4, at most 720p – a format
every browser plays – and at most MAX_SECONDS long. It is downloaded into a
temporary folder first; `<id>.mp4` is moved into the cache, then `<id>.json`
(the list's title, YouTube's, the length) is written – the library counts a
song as downloaded only when both are there, so an interrupted run never
leaves a half song behind. One song failing doesn't stop the others.

YouTube changes often and yt-dlp follows; when downloads start failing,
update the pinned yt-dlp (src/backend/pyproject.toml) and rebuild the image,
in the week before the event (tech-spec 5.2).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dod.music.library import SONGS_FILE, Library, Song, SongListError
from dod.settings import Settings, SettingsError

MAX_SECONDS = 7 * 60
MAX_HEIGHT = 720
# H.264 + AAC in mp4 first; a single file in that format if there is no pair
FORMAT = (
    f"bv*[vcodec^=avc1][height<={MAX_HEIGHT}][ext=mp4]+ba[acodec^=mp4a][ext=m4a]"
    f"/b[vcodec^=avc1][acodec^=mp4a][height<={MAX_HEIGHT}][ext=mp4]"
)


class TooLong(Exception):
    pass


@dataclass(frozen=True)
class Fetched:
    video: Path  # in the temporary folder
    youtube_title: str
    length: float  # seconds


Fetch = Callable[[Song, Path], Fetched]


def yt_dlp_options(folder: Path) -> dict[str, object]:
    """What yt-dlp gets; separate, so a test can check it without the internet."""
    return {
        "format": FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(folder / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "overwrites": True,
    }


def fetch_with_yt_dlp(song: Song, folder: Path) -> Fetched:
    """One song from YouTube into `folder`. Raises TooLong, or yt-dlp's errors."""
    import yt_dlp  # here: the backend itself never needs it

    with yt_dlp.YoutubeDL(yt_dlp_options(folder)) as ydl:
        info = ydl.extract_info(song.url, download=False)
        length = float(info.get("duration") or 0)
        if length > MAX_SECONDS:
            raise TooLong(f"{length / 60:.1f} min, at most {MAX_SECONDS // 60}")
        ydl.process_ie_result(info, download=True)
    video = folder / f"{song.id}.mp4"
    if not video.is_file():
        raise RuntimeError("yt-dlp finished without an .mp4 (no H.264 + AAC version?)")
    return Fetched(video=video, youtube_title=str(info.get("title") or ""), length=length)


def download(library: Library, songs: list[Song], fetch: Fetch = fetch_with_yt_dlp,
             say: Callable[[str], None] = print) -> list[str]:
    """Downloads `songs` that aren't downloaded yet. Returns the ids that failed."""
    library.cache_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    todo = [s for s in songs if not library.ready(s.id)]
    for song in songs:
        if song not in todo:
            say(f"  have  {song.id}  {song.title}")
    for n, song in enumerate(todo, start=1):
        say(f"  get   {song.id}  {song.title}  ({n}/{len(todo)})")
        try:
            with tempfile.TemporaryDirectory(dir=library.cache_dir, prefix=".download-") as tmp:
                got = fetch(song, Path(tmp))
                if got.length > MAX_SECONDS:
                    raise TooLong(f"{got.length / 60:.1f} min, at most {MAX_SECONDS // 60}")
                shutil.move(got.video, library.cache_dir / f"{song.id}.mp4")
                meta = {"id": song.id, "title": song.title, "youtube_title": got.youtube_title, "length": got.length}
                (library.cache_dir / f"{song.id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                                                    encoding="utf-8")
            say(f"  done  {song.id}  {got.length / 60:.1f} min")
        except TooLong as e:
            failed.append(song.id)
            say(f"  SKIP  {song.id}  too long: {e}")
        except Exception as e:  # yt-dlp's own errors, the network, the disk
            failed.append(song.id)
            say(f"  FAIL  {song.id}  {type(e).__name__}: {e}")
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="./dod songs", description="Download the songs missing from the cache.")
    parser.add_argument("ids", nargs="*", help="only these songs (they must be on the list)")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        library = Library.from_file(SONGS_FILE, settings.cache_dir)
    except (SettingsError, SongListError) as e:
        print(f"dod: {e}", file=sys.stderr)
        return 1
    songs = library.songs
    if args.ids:
        unknown = [i for i in args.ids if library.song(i) is None]
        if unknown:
            print(f"dod: not on the list ({SONGS_FILE.name}): {', '.join(unknown)}", file=sys.stderr)
            return 1
        songs = [s for s in songs if s.id in args.ids]
    print(f"songs: {len(songs)} on the list, cache: {settings.cache_dir}")
    failed = download(library, songs)
    print(f"{len(songs) - len(failed)} of {len(songs)} ready" + (f", failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
