import httpx


class HttpClientManager:
    """
    A centralized manager for the asynchronous HTTP client.

    This class follows the Singleton pattern to manage a single instance of
    `httpx.AsyncClient`. Reusing a single client across the application
    allows for connection pooling, which significantly improves performance
    and resource management.
    """

    client: httpx.AsyncClient = None

    @classmethod
    async def init_client(cls):
        """
        Initializes the shared HTTP client if it doesn't exist or is closed.

        The client is configured with a default timeout of 10.0 seconds.
        This method should typically be called during the application's
        startup sequence.
        """
        if cls.client is None or cls.client.is_closed:
            cls.client = httpx.AsyncClient(timeout=10.0)

    @classmethod
    async def close_client(cls):
        """
        Gracefully closes the shared HTTP client and releases its resources.

        This method should be called during the application's shutdown
        sequence to ensure all connections are properly terminated.
        """
        if cls.client:
            await cls.client.aclose()
            cls.client = None
