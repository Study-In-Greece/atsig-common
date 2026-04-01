from abc import ABC, abstractmethod
from typing import Literal, Optional

# Define allowed bucket types for strict type checking
BucketType = Literal["private", "public"]


class BaseStorage(ABC):
    """
    Abstract base class defining the standard interface for storage providers.
    All storage implementations (S3, Local, etc.) must implement these methods.
    """

    @abstractmethod
    async def upload(
        self,
        file_data: bytes,
        key: str,
        bucket_type: BucketType = "private",
        content_type: Optional[str] = None,
    ) -> str:
        """Uploads a file to the storage provider."""
        pass

    @abstractmethod
    async def get_presigned_url(self, key: str, expires: int = 3600) -> str:
        """Generates a temporary signed URL for secure access to private files."""
        pass

    @abstractmethod
    async def delete(self, key: str, bucket_type: BucketType = "private"):
        """Deletes a file from the storage provider."""
        pass
