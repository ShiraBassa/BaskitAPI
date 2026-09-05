
"""Small Ollama HTTP client used by Baskit's local AI components."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .response_parser import decode_json_response


LOCAL_AI_URL = os.getenv(
    "LOCAL_AI_URL",
    "http://127.0.0.1:11434/api/chat",
)
LOCAL_AI_MODEL = os.getenv(
    "LOCAL_AI_MODEL",
    "aya-expanse:8b",
)


class OllamaClient:
    def __init__(
        self,
        url: str | None = None,
        model: str | None = None,
    ):
        self.url = url or LOCAL_AI_URL
        self.model = model or LOCAL_AI_MODEL

    def payload(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        num_predict: int,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "keep_alive": "10m",
            "stream": False,
            "think": False,
            "format": schema,
            "messages": [
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": user,
                },
            ],
            "options": {
                "temperature": 0,
                "num_predict": num_predict,
                "num_ctx": 4096,
            },
        }

    def chat(
        self,
        payload: dict[str, Any],
        timeout: int = 180,
        retries: int = 2,
    ) -> tuple[Any, str]:
        for attempt in range(retries + 1):
            try:
                request = urllib.request.Request(
                    self.url,
                    data=json.dumps(
                        payload,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )

                with urllib.request.urlopen(
                    request,
                    timeout=timeout,
                ) as response:
                    data = json.loads(
                        response.read().decode("utf-8")
                    )

                raw = data.get(
                    "message",
                    {},
                ).get(
                    "content",
                    "",
                )

                return decode_json_response(raw), raw

            except (
                urllib.error.URLError,
                TimeoutError,
                OSError,
                json.JSONDecodeError,
            ):
                if attempt >= retries:
                    raise

                time.sleep(attempt + 1)

        raise RuntimeError("Ollama request failed")
