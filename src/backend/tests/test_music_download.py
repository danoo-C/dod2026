"""The downloader, without the internet: a fake fetch stands in for yt-dlp
(plan step 8). The real download is checked by hand with ./dod songs."""

import json

from dod.music.download import FORMAT, MAX_SECONDS, Fetched, TooLong, download, yt_dlp_options
from dod.music.library import Library, Song

SONGS = [Song("y6120QOlsfU", "Sandstorm"), Song("dQw4w9WgXcQ", "Never Gonna"), Song("9bZkp7q19f0", "Gangnam")]


def fake_fetch(lengths, calls):
    def fetch(song, folder):
        calls.append(song.id)
        length = lengths.get(song.id, 200.0)
        if length is None:
            raise RuntimeError("HTTP Error 403")
        video = folder / f"{song.id}.mp4"
        video.write_bytes(b"\x00" * 64)
        return Fetched(video=video, youtube_title=f"{song.title} (Official Video)", length=length)
    return fetch


def test_downloads_what_is_missing_and_a_second_run_nothing(tmp_path):
    library = Library(SONGS, tmp_path / "cache")
    calls = []
    assert download(library, SONGS, fake_fetch({}, calls), say=lambda _: None) == []
    assert calls == [s.id for s in SONGS]
    assert all(library.ready(s.id) for s in SONGS)
    meta = json.loads((tmp_path / "cache" / "dQw4w9WgXcQ.json").read_text())
    assert meta == {"id": "dQw4w9WgXcQ", "title": "Never Gonna", "youtube_title": "Never Gonna (Official Video)",
                    "length": 200.0}
    calls.clear()
    assert download(library, SONGS, fake_fetch({}, calls), say=lambda _: None) == []
    assert calls == []  # everything is there


def test_one_failing_song_doesnt_stop_the_others(tmp_path):
    library = Library(SONGS, tmp_path)
    said = []
    failed = download(library, SONGS, fake_fetch({"dQw4w9WgXcQ": None}, []), say=said.append)
    assert failed == ["dQw4w9WgXcQ"]
    assert library.ready("y6120QOlsfU") and library.ready("9bZkp7q19f0") and not library.ready("dQw4w9WgXcQ")
    assert any("FAIL  dQw4w9WgXcQ" in s and "403" in s for s in said)
    assert not list(tmp_path.glob(".download-*"))  # no temporary folder left behind


def test_a_song_over_7_minutes_is_skipped(tmp_path):
    library = Library(SONGS[:1], tmp_path)
    said = []
    assert download(library, SONGS[:1], fake_fetch({"y6120QOlsfU": MAX_SECONDS + 1}, []), say=said.append) == ["y6120QOlsfU"]
    assert not library.ready("y6120QOlsfU") and not (tmp_path / "y6120QOlsfU.mp4").exists()
    assert any("too long" in s for s in said)


def test_too_long_from_yt_dlp_itself_is_skipped_too(tmp_path):
    def fetch(song, folder):
        raise TooLong("9.0 min, at most 7")
    assert download(Library(SONGS[:1], tmp_path), SONGS[:1], fetch, say=lambda _: None) == ["y6120QOlsfU"]


def test_an_interrupted_download_leaves_no_half_song(tmp_path):
    library = Library(SONGS[:1], tmp_path)

    def fetch(song, folder):
        (folder / f"{song.id}.mp4").write_bytes(b"half")
        raise KeyboardInterrupt if False else OSError("disk full")
    download(library, SONGS[:1], fetch, say=lambda _: None)
    assert not (tmp_path / "y6120QOlsfU.mp4").exists() and not library.ready("y6120QOlsfU")


def test_yt_dlp_asks_for_h264_and_aac_in_mp4_at_most_720p(tmp_path):
    options = yt_dlp_options(tmp_path)
    assert options["format"] == FORMAT
    for want in ("vcodec^=avc1", "acodec^=mp4a", "height<=720", "ext=mp4"):
        assert want in FORMAT
    assert options["merge_output_format"] == "mp4" and options["noplaylist"] is True
    assert str(options["outtmpl"]).startswith(str(tmp_path))


def test_yt_dlp_and_deno_are_in_the_image():
    import shutil

    import yt_dlp

    assert yt_dlp.version.__version__ == "2026.10.21"
    assert shutil.which("deno") is not None  # yt-dlp needs it for YouTube
    assert shutil.which("ffmpeg") is not None  # it merges video and audio
