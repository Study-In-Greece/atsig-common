import httpx


class HttpClientManager:
    client: httpx.AsyncClient = None

    @classmethod
    async def init_client(cls):
        if cls.client is None or cls.client.is_closed:
            cls.client = httpx.AsyncClient(timeout=10.0)

    @classmethod
    async def close_client(cls):
        if cls.client:
            await cls.client.aclose()
            cls.client = None
