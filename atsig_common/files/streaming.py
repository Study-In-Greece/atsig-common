import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO

import aiofiles


def iter_file(file: BinaryIO, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    """Yields a file object in chunks and closes it when done or abandoned."""
    try:
        while chunk := file.read(chunk_size):
            yield chunk
    finally:
        file.close()


@contextmanager
def temp_file(suffix: str = "") -> Iterator[str]:
    """
    A path to an empty temporary file, deleted when the block ends, whatever
    happens inside it (an error included).
    """
    path = TempFileHelper.get_temp_path(suffix)
    try:
        yield path
    finally:
        TempFileHelper.delete_temp(path)


class TempFileHelper:
    """
    Temporary files that outlive the function that makes them (a file answered with
    FileResponse is deleted by a background task). If the file is used inside one
    block, prefer `temp_file`, which cleans up by itself.
    """

    @staticmethod
    def get_temp_path(suffix: str) -> str:
        """Creates an empty temp file and returns its path."""
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        return path

    @staticmethod
    async def save_temp(content: bytes, suffix: str) -> str:
        """Saves content to a local temp file for immediate processing."""
        path = TempFileHelper.get_temp_path(suffix)
        try:
            async with aiofiles.open(path, "wb") as f:
                await f.write(content)
        except BaseException:
            TempFileHelper.delete_temp(path)
            raise
        return path

    @staticmethod
    def delete_temp(path: str) -> None:
        """Deletes a local temp file (nothing happens if it is already gone)."""
        if path and os.path.exists(path):
            os.remove(path)
