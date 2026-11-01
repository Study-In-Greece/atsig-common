import pytest

from atsig_common.storage.s3 import S3Storage


class FakeS3Client:
    def __init__(self):
        self.exits = 0

    async def __aexit__(self, *exc_info):
        self.exits += 1


async def test_s3_stop_forgets_the_client():
    storage = S3Storage("http://r2", "key", "secret", r2_private_bucket="bucket")
    client = FakeS3Client()
    storage._s3_client = client

    await storage.stop()
    await storage.stop()  # a second stop is harmless

    assert client.exits == 1
    with pytest.raises(RuntimeError, match="not initialized"):
        storage._ensure_client()
