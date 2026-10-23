"""Small synchronous Ollama HTTP adapter; model invocations are not replayed tools."""

import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


class ModelError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, model="qwen3:4b", host="http://127.0.0.1:11434", timeout=120,
                 temperature=0.2, num_ctx=8192, num_predict=2048, retries=2):
        parts = urllib.parse.urlsplit(host)
        if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username
                or parts.password or parts.query or parts.fragment or parts.path not in ("", "/")):
            raise ValueError("host must be an http(s) origin, e.g. http://127.0.0.1:11434")
        if timeout <= 0 or not 0 <= retries <= 5 or num_ctx < 512 or num_predict < 32:
            raise ValueError("Invalid model timeout, retry, or token budget")
        self.host, self.model = host.rstrip("/"), model
        self.timeout, self.retries = timeout, retries
        self.options = dict(temperature=temperature, num_ctx=num_ctx, num_predict=num_predict)
        # Local model traffic must not accidentally use a system HTTP proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(self.host + path, data=data,
                                             headers={"Content-Type": "application/json"})
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ModelError("Ollama response exceeds 4 MiB")
                result = json.loads(raw)
                if not isinstance(result, dict) or result.get("error"):
                    raise ModelError(str(result.get("error", "Expected an object"))
                                     if isinstance(result, dict) else "Expected a JSON object")
                return result
            except urllib.error.HTTPError as exc:
                detail = exc.read(2048).decode("utf-8", "replace")
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == self.retries:
                    raise ModelError(f"Ollama HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, http.client.HTTPException) as exc:
                if attempt == self.retries:
                    raise ModelError(f"Cannot reach Ollama at {self.host}: {exc}") from exc
            except (ValueError, UnicodeError) as exc:
                raise ModelError(f"Ollama returned invalid JSON: {exc}") from exc
            time.sleep(0.3 * (attempt + 1))
        raise ModelError("Ollama retry budget exhausted")

    def chat(self, messages, tools=None, response_format=None):
        body = dict(model=self.model, messages=messages, stream=False, options=self.options)
        if tools:
            body["tools"] = tools
        if response_format is not None:
            body["format"] = response_format
        result = self._request("/api/chat", body)
        if result.get("done") is not True:
            raise ModelError("Incomplete Ollama response; no tool from this response was executed")
        if result.get("done_reason") in ("length", "max_tokens"):
            raise ModelError("Model response hit the output limit; raise num_predict or shorten the task")
        message = result.get("message")
        if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
            raise ModelError("Ollama response has no assistant message")
        if not isinstance(message.get("content", ""), str):
            raise ModelError("Ollama returned non-text content")
        return message

    def models(self):
        result = self._request("/api/tags")
        models = result.get("models", [])
        if not isinstance(models, list):
            raise ModelError("Invalid Ollama model list")
        return [item["name"] for item in models if isinstance(item, dict) and isinstance(item.get("name"), str)]
