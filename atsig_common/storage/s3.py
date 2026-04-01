import aioboto3
from typing import Optional
from .base import BaseStorage, BucketType


class S3Storage(BaseStorage):
    """
    S3-compatible storage implementation for Cloudflare R2 using aioboto3.
    Designed for high-performance asynchronous file operations with lifespan management.
    """

    def __init__(
        self,
        r2_endpoint_url: str,
        r2_access_key_id: str,
        r2_secret_access_key: str,
        r2_private_bucket: Optional[str] = None,
        r2_public_bucket: Optional[str] = None,
    ):
        """
        Initializes the storage manager with Cloudflare R2 credentials.

        Args:
            r2_endpoint_url: Cloudflare Endpoint URL.
            r2_access_key_id: R2 API Access Key.
            r2_secret_access_key: R2 API Secret Key.
            r2_private_bucket: Optional name of the private bucket.
            r2_public_bucket: Optional name of the public bucket.
        """
        self.r2_endpoint_url = r2_endpoint_url
        self.r2_access_key_id = r2_access_key_id
        self.r2_secret_access_key = r2_secret_access_key
        self.r2_private_bucket = r2_private_bucket
        self.r2_public_bucket = r2_public_bucket

        self.session = aioboto3.Session()
        self._s3_client = None

    async def start(self):
        """
        Initializes the asynchronous S3 client.
        Should be called within the FastAPI lifespan startup.
        """
        self._s3_client = await self.session.client(
            "s3",
            endpoint_url=self.r2_endpoint_url,
            aws_access_key_id=self.r2_access_key_id,
            aws_secret_access_key=self.r2_secret_access_key,
        ).__aenter__()

    async def stop(self):
        """
        Gracefully closes the S3 client connection pool.
        Should be called within the FastAPI lifespan shutdown.
        """
        if self._s3_client:
            await self._s3_client.__aexit__(None, None, None)

    def _ensure_client(self):
        """
        Internal sanity check to ensure the client is initialized before use.

        Raises:
            RuntimeError: If the client hasn't been started.
        """
        if self._s3_client is None:
            raise RuntimeError(
                "S3Storage client not initialized. Make sure to call start() "
                "within the application lifespan."
            )

    def _get_bucket_name(self, bucket_type: BucketType) -> str:
        """
        Resolves the bucket name based on the requested type.

        Raises:
            RuntimeError: If the requested bucket is not configured in settings.
        """
        if bucket_type == "private":
            if not self.r2_private_bucket:
                raise RuntimeError("Private bucket is not configured for this API.")
            return self.r2_private_bucket

        if not self.r2_public_bucket:
            raise RuntimeError("Public bucket is not configured for this API.")
        return self.r2_public_bucket

    async def upload(
        self,
        file_data: bytes,
        key: str,
        bucket_type: BucketType = "private",
        content_type: Optional[str] = None,
    ) -> str:
        """
        Uploads binary data to the specified bucket.

        Returns:
            str: The storage key (path) of the uploaded file.
        """
        self._ensure_client()
        bucket = self._get_bucket_name(bucket_type)

        params = {"Bucket": bucket, "Key": key, "Body": file_data}
        if content_type:
            params["ContentType"] = content_type

        await self._s3_client.put_object(**params)
        return key

    async def get_presigned_url(self, key: str, expires: int = 3600) -> str:
        """
        Generates a temporary signed URL for a file in the private bucket.

        Args:
            key: The storage key of the file.
            expires: Time in seconds until the URL expires (default: 1 hour).
        """
        self._ensure_client()
        bucket = self._get_bucket_name("private")
        return await self._s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
        )

    async def delete(self, key: str, bucket_type: BucketType = "private"):
        """Deletes an object from the specified bucket."""
        self._ensure_client()
        bucket = self._get_bucket_name(bucket_type)
        await self._s3_client.delete_object(Bucket=bucket, Key=key)
