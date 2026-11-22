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
    timeout: httpx.Timeout = httpx.Timeout(10.0, connect=5.0, pool=5.0)
    limits: httpx.Limits = httpx.Limits(max_connections=100)

    @classmethod
    def configure(
        cls,
        *,
        connect_timeout: float = 5.0,
        timeout: float = 10.0,
        pool_timeout: float = 5.0,
        max_connections: int = 100,
    ) -> None:
        """
        Sets the timeouts and the pool of the shared client. Call it before
        `init_client` (`build_core` does it from the settings). A timeout is a wait,
        not a total: `timeout` is the time to read and to write, `pool_timeout` the time
        to wait for a free connection.
        """
        cls.timeout = httpx.Timeout(timeout, connect=connect_timeout, pool=pool_timeout)
        cls.limits = httpx.Limits(max_connections=max_connections)

    @classmethod
    async def init_client(cls):
        """
        Initializes the shared HTTP client if it doesn't exist or is closed.

        The client uses `timeout` and `limits` (see `configure`).
        This method should typically be called during the application's
        startup sequence.
        """
        if cls.client is None or cls.client.is_closed:
            cls.client = httpx.AsyncClient(timeout=cls.timeout, limits=cls.limits)

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
