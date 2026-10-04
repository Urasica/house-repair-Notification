"""Fixed-destination embeddings client; no SDK retries, logs, or persistent query cache."""

import asyncio
import math
from dataclasses import dataclass

import httpx

from app.core.config import Settings


class EmbeddingUnavailable(Exception):
    """Safe error code only: never propagate provider response text or credentials."""


@dataclass(frozen=True)
class EmbeddedBatch:
    vectors: list[list[float]]
    tokens: int


def validate_vector(vector, dimensions: int):
    if (
        not isinstance(vector, list)
        or len(vector) != dimensions
        or any(type(v) not in (float, int) or not math.isfinite(v) for v in vector)
        or not any(vector)
    ):
        raise EmbeddingUnavailable("INVALID_VECTOR")


class Embeddings:
    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    async def embed(self, texts: list[str], *, timeout: float = 5) -> EmbeddedBatch:
        settings = self.settings
        if not settings.openai_enabled or not settings.openai_api_key.get_secret_value():
            raise EmbeddingUnavailable("OPENAI_DISABLED")
        # UTF-8 byte count is a conservative BPE token upper bound. Never truncate a source.
        if (
            not texts
            or len(texts) > 32
            or any(not t.strip() or len(t.encode("utf-8")) > 8191 for t in texts)
            or sum(len(t.encode("utf-8")) for t in texts) > 250000
        ):
            raise EmbeddingUnavailable("INPUT_LIMIT")
        try:
            async with (
                asyncio.timeout(timeout),
                httpx.AsyncClient(
                    timeout=timeout,
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
            ):
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={
                        "Authorization": "Bearer " + settings.openai_api_key.get_secret_value()
                    },
                    json={
                        "model": settings.openai_embedding_model,
                        "dimensions": settings.embedding_dimensions,
                        "encoding_format": "float",
                        "input": texts,
                    },
                )
                if response.status_code != 200:
                    raise EmbeddingUnavailable("PROVIDER_ERROR")
                data = response.json()
            if data["model"] != settings.openai_embedding_model:
                raise EmbeddingUnavailable("MODEL_MISMATCH")
            rows = sorted(data["data"], key=lambda row: row["index"])
            if [row["index"] for row in rows] != list(range(len(texts))):
                raise EmbeddingUnavailable("INVALID_RESPONSE")
            vectors = [row["embedding"] for row in rows]
            for vector in vectors:
                validate_vector(vector, settings.embedding_dimensions)
            tokens = data["usage"]["total_tokens"]
            if type(tokens) is not int or tokens < 0:
                raise EmbeddingUnavailable("INVALID_USAGE")
            return EmbeddedBatch(vectors, tokens)
        except (httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError):
            raise EmbeddingUnavailable("EMBEDDING_FAILED") from None
