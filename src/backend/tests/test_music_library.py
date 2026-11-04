"""The song list and the cache (plan step 8)."""

import json

import pytest

from dod.music.library import SONGS_FILE, Library, Song, SongListError, parse, youtube_id

ID = "dQw4w9WgXcQ"


def downloaded(cache, song_id, length=213.0):
    (cache / f"{song_id}.mp4").write_bytes(b"\x00" * 100)
    (cache / f"{song_id}.json").write_text(json.dumps({"id": song_id, "title": "x", "length": length}))


# --- songs.txt ----------------------------------------------------------------


def test_the_real_list_parses():
    songs = parse(SONGS_FILE.read_text(encoding="utf-8"))
    assert len(songs) == 10
    assert songs[0] == Song(id="y6120QOlsfU", title="Darude – Sandstorm")
    assert len({s.id for s in songs}) == len(songs)


@pytest.mark.parametrize("link", [
    f"https://www.youtube.com/watch?v={ID}",
    f"https://youtube.com/watch?v={ID}&t=42s",
    f"https://m.youtube.com/watch?v={ID}",
    f"https://music.youtube.com/watch?v={ID}",
    f"https://youtu.be/{ID}",
    f"https://youtu.be/{ID}?si=abc",
    f"https://www.youtube.com/shorts/{ID}",
])
def test_links_give_their_id(link):
    assert youtube_id(link) == ID


@pytest.mark.parametrize("link", [
    "dQw4w9WgXcQ",
    "https://vimeo.com/123",
    "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/watch?v=../../etc/pa",
    "ftp://youtu.be/dQw4w9WgXcQ",
    "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
])
def test_anything_else_is_no_link(link):
    assert youtube_id(link) is None


def test_comments_and_blank_lines_are_left_out():
    assert parse(f"# songs\n\n  https://youtu.be/{ID}   Never Gonna  \n") == [Song(ID, "Never Gonna")]


def test_every_bad_line_is_named_at_once():
    text = "\n".join([
        f"https://youtu.be/{ID}  Fine",
        "https://vimeo.com/1  Nope",
        "https://youtu.be/y6120QOlsfU",
        f"https://youtu.be/{ID}  Again",
        "https://youtu.be/9bZkp7q19f0  " + "x" * 41,
    ])
    with pytest.raises(SongListError) as e:
        parse(text)
    assert [p.split(":")[0] for p in e.value.problems] == ["line 2", "line 3", "line 4", "line 5"]
    assert "short title" in e.value.problems[1] and "line 1" in e.value.problems[2]


# --- the cache ----------------------------------------------------------------


def test_a_song_is_ready_with_both_files(tmp_path):
    library = Library([Song(ID, "Never Gonna")], tmp_path)
    assert not library.ready(ID) and library.video(ID) is None
    (tmp_path / f"{ID}.mp4").write_bytes(b"x")
    assert not library.ready(ID)  # the video alone is a half download
    downloaded(tmp_path, ID)
    assert library.ready(ID) and library.length(ID) == 213.0
    assert library.video(ID) == tmp_path / f"{ID}.mp4"


def test_a_broken_meta_file_is_not_ready(tmp_path):
    library = Library([Song(ID, "Never Gonna")], tmp_path)
    (tmp_path / f"{ID}.mp4").write_bytes(b"x")
    (tmp_path / f"{ID}.json").write_text("{not json")
    assert not library.ready(ID)
    (tmp_path / f"{ID}.json").write_text(json.dumps({"length": 0}))
    assert not library.ready(ID)


def test_ids_not_on_the_list_never_reach_the_disk(tmp_path):
    downloaded(tmp_path, "y6120QOlsfU")  # in the cache, but not on this list
    library = Library([Song(ID, "Never Gonna")], tmp_path)
    for bad in ("y6120QOlsfU", "../etc/passwd", "", None):
        assert library.video(bad) is None and not library.ready(bad)


def test_the_infos_for_the_phone(tmp_path):
    downloaded(tmp_path, ID)
    library = Library([Song("y6120QOlsfU", "Sandstorm"), Song(ID, "Never Gonna")], tmp_path)
    assert [i.model_dump() for i in library.infos()] == [
        {"id": "y6120QOlsfU", "title": "Sandstorm", "length": None, "ready": False},
        {"id": ID, "title": "Never Gonna", "length": 213.0, "ready": True},
    ]
    assert [s.id for s in library.missing()] == ["y6120QOlsfU"]
