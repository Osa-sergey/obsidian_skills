"""Embeddings client: a local OpenAI-compatible HTTP server (LM Studio).

ADR-0009: this project stays a thin HTTP client here exactly like it does
for Omnisearch, rather than embedding PyTorch/sentence-transformers - the
actual model (`qwen3-embedding-0.6b-mlx` by default, matching
defaults.md's named model) runs inside LM Studio, reached via its
OpenAI-compatible `POST /v1/embeddings`.

Two things about LM Studio specifically, confirmed by hand while wiring
this up, worth knowing before debugging a fresh "no models loaded":

1. The server requires `Authorization: Bearer <token>` once an API key is
   configured (LM Studio's default in recent versions) - `EmbeddingsConfig
   .api_key` in the vault profile, sent as a Bearer token here.
2. `lms load`/`lms ps` reporting a model as loaded does not always mean
   the HTTP server process serving `/v1/embeddings` sees it the same way -
   loading the model from LM Studio's own GUI (Developer -> Server tab)
   was what actually made requests succeed in the one case this was
   observed. `ping()` exists so callers find this out with one cheap call
   instead of a confusing failure deep into indexing a whole vault.
   Also: never send a chat/completions request to an embedding-only model
   to "test" it - it is not a valid operation for that model type and was
   observed to leave the server's next request hanging/erroring even for
   `/v1/embeddings`; use `ping()` instead.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import List, Optional


class EmbeddingUnavailable(RuntimeError):
    """The embeddings server is unreachable, refused, timed out, or has no
    model actually loaded and serving - see module docstring point 2."""


@dataclass
class EmbeddingResult:
    vectors: List[List[float]]
    dimension: int
    model: str


class EmbeddingClient:
    def __init__(
        self, host: str = "127.0.0.1", port: int = 1234, model: str = "qwen3-embedding-0.6b-mlx",
        api_key: str = "", timeout: float = 30.0,
    ):
        self.host = host
        self.port = port
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        url = f"http://{self.host}:{self.port}{path}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingUnavailable(
                f"embeddings server at {self.host}:{self.port} returned HTTP {exc.code}: {detail}. "
                "If this says 'no models loaded', load the model from LM Studio's own GUI "
                "(Developer -> Server), not just `lms load` - see embeddings.py's module docstring."
            ) from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            raise EmbeddingUnavailable(
                f"embeddings server not reachable at {self.host}:{self.port} ({exc}). "
                "Is LM Studio running with its local server turned on?"
            ) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EmbeddingUnavailable(f"embeddings server returned non-JSON response: {exc}") from exc

    def embed(self, texts: List[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult([], 0, self.model)
        data = self._post("/v1/embeddings", {"model": self.model, "input": texts})
        items = data.get("data")
        if not items:
            raise EmbeddingUnavailable(f"embeddings server returned no 'data': {data}")
        # LM Studio preserves input order via the 'index' field; sort just
        # in case a future server implementation doesn't guarantee it.
        items = sorted(items, key=lambda it: it.get("index", 0))
        vectors = [it["embedding"] for it in items]
        dim = len(vectors[0]) if vectors else 0
        return EmbeddingResult(vectors, dim, data.get("model", self.model))

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text]).vectors[0]

    def ping(self) -> bool:
        try:
            self.embed(["ping"])
            return True
        except EmbeddingUnavailable:
            return False
