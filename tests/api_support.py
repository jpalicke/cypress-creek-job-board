# ABOUTME: A small synchronous client that drives a real ASGI app in process through httpx.
# ABOUTME: It uses the real app and httpx's ASGI transport, with no mocked component.
import asyncio
from typing import Any

import httpx
from fastapi import FastAPI

LOOPBACK_BASE = "http://127.0.0.1:5309"


class ApiClient:
    """Sends each request through the app's ASGI interface and returns the real response."""

    def __init__(
        self, app: FastAPI, base_url: str = LOOPBACK_BASE, *, raise_exceptions: bool = False
    ) -> None:
        self.app = app
        self._base_url = base_url
        self._raise_exceptions = raise_exceptions

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(
                app=self.app, raise_app_exceptions=self._raise_exceptions
            )
            async with httpx.AsyncClient(transport=transport, base_url=self._base_url) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(send())

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("OPTIONS", url, **kwargs)
