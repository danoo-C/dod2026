"""Sessions and the internal key (docs/backend.md 9)."""

import pytest

from dod.control.sessions import (
    MAIN,
    SESSION_COOKIE,
    cookie_options,
    key_matches,
    new_token,
    public_id,
    session_token,
    short,
    valid_token,
)


def test_tokens_are_random_128_bits():
    a, b = new_token(), new_token()
    assert a != b and len(a) == 32 and valid_token(a)


def test_only_valid_tokens_are_read():
    token = new_token()
    assert session_token({SESSION_COOKIE: token}) == token
    for bad in ("", "abc", token.upper(), token + "0", "../" + token[3:], None):
        assert session_token({SESSION_COOKIE: bad} if bad is not None else {}) is None


def test_the_public_id_hides_the_token():
    token = new_token()
    pid = public_id(token)
    assert pid == public_id(token) and len(pid) == 12
    assert pid not in token  # a photo of the logs on the public screen gives nothing away
    with pytest.raises(ValueError):
        public_id("not a token")


def test_short():
    assert short("7f3a91c2b4d5") == "7f3a"
    assert short(MAIN) == "main" and short(None) is None


def test_the_internal_key():
    assert key_matches("s3cret", "s3cret")
    assert not key_matches("s3cre", "s3cret") and not key_matches("", "s3cret") and not key_matches(None, "s3cret")
    assert key_matches("klíč", "klíč")  # not only ASCII


def test_cookie_options():
    assert cookie_options()["httponly"] is True and cookie_options()["samesite"] == "lax"
