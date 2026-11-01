import io
import os
from pathlib import Path

import pytest

from atsig_common.files.keys import is_key_under_prefix
from atsig_common.files.signatures import (
    EXTENSIONS,
    SIGNATURE_BYTES,
    detect_file_type,
)
from atsig_common.files.streaming import TempFileHelper, iter_file, temp_file


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"\xff\xd8\xff\xe0 jfif", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n rest", "image/png"),
        (b"%PDF-1.7 rest", "application/pdf"),
        (b"\xef\xbb\xbf\n%PDF-1.4", "application/pdf"),  # a BOM and a line before it
        (b"<html><script>alert(1)</script>", None),
        (b"", None),
        (b"MZ\x90\x00 an executable", None),
    ],
)
def test_the_type_comes_from_the_bytes(head, expected):
    assert detect_file_type(head) == expected


def test_a_pdf_header_after_the_first_kilobyte_is_not_a_pdf():
    assert detect_file_type(b"x" * SIGNATURE_BYTES + b"%PDF-1.7") is None


def test_every_detected_type_has_an_extension():
    assert set(EXTENSIONS) == {"application/pdf", "image/png", "image/jpeg"}


@pytest.mark.parametrize(
    "key",
    [
        "applications/1/document/2/a.pdf",
        "applications/1/a.pdf",
    ],
)
def test_plain_keys_below_the_prefix_are_accepted(key):
    assert is_key_under_prefix(key, "applications/1/")


@pytest.mark.parametrize(
    "key",
    [
        "applications/1/../2/a.pdf",  # traversal
        "applications/1/./a.pdf",
        "applications/1//a.pdf",  # empty segment
        "applications/1/a%2e%2e/b",  # percent sign
        "applications/1/a\\b.pdf",  # backslash
        "applications/1/a\nb.pdf",  # control character
        "applications/10/a.pdf",  # another application with the same start
        "applications/1",  # the prefix itself
    ],
)
def test_keys_that_could_leave_the_prefix_are_refused(key):
    assert not is_key_under_prefix(key, "applications/1/")


def test_a_prefix_without_a_trailing_slash_is_refused():
    assert not is_key_under_prefix("applications/10/a.pdf", "applications/1")


def test_iter_file_yields_chunks_and_closes_the_file():
    file = io.BytesIO(b"abcdefgh")

    assert list(iter_file(file, chunk_size=3)) == [b"abc", b"def", b"gh"]
    assert file.closed


def test_iter_file_closes_the_file_when_abandoned():
    file = io.BytesIO(b"abcdefgh")
    chunks = iter_file(file, chunk_size=3)
    next(chunks)

    chunks.close()

    assert file.closed


def test_temp_file_is_deleted_after_the_block():
    with temp_file(".pdf") as path:
        assert os.path.exists(path) and path.endswith(".pdf")

    assert not os.path.exists(path)


def test_temp_file_is_deleted_when_the_block_fails():
    with pytest.raises(RuntimeError), temp_file(".csv") as path:
        raise RuntimeError("generation failed")

    assert not os.path.exists(path)


async def test_save_temp_writes_the_content_and_delete_temp_is_idempotent():
    path = await TempFileHelper.save_temp(b"hello", ".txt")

    assert Path(path).read_bytes() == b"hello"
    TempFileHelper.delete_temp(path)
    TempFileHelper.delete_temp(path)  # already gone: nothing happens
    assert not os.path.exists(path)
