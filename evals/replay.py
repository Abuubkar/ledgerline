"""Record every model answer during a live eval, and replay them without Ollama.

It wraps the one network call Ledgerline makes to the model (`ollama.AsyncClient.chat`), so everything of ours
around it (prompt budgeting, truncation checks, parsing, repair, the agent loop) runs the same in both modes.
Answers are stored under evals/recordings/<model>/ by a hash of the request: model, messages (images included),
response format, tools and options. A changed prompt or code path that sends a different request has no
recording, and replay stops with a message to run the eval live.

Timing comes from Ollama's own durations in the recorded answer, not the clock, so a replay reports exactly the
latency and tokens/sec of the live run.
"""

import asyncio
import contextvars
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import ollama

RECORDINGS = Path(__file__).parent / "recordings"
# Which eval case the current model call belongs to, so its time and tokens are added to that case.
current_case: contextvars.ContextVar[str] = contextvars.ContextVar("current_case", default="")


class MissingRecording(RuntimeError):
    pass


def _plain(value):
    """Request values as JSON-able data: pydantic objects dumped, image bytes hashed."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(exclude_none=True)
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in sorted(value.items()) if v is not None}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def request_key(kwargs: dict) -> str:
    wanted = {k: kwargs.get(k) for k in ("model", "messages", "format", "tools", "options", "think")}
    return hashlib.sha256(json.dumps(_plain(wanted), sort_keys=True, default=str).encode()).hexdigest()


class Recorder:
    def __init__(self, live: bool, root: Path = RECORDINGS):
        self.live, self.root = live, root
        self.stats: dict[str, list[dict]] = defaultdict(list)  # case -> one entry per model call
        self.recorded = self.replayed = 0
        self._original = ollama.AsyncClient.chat

    def install(self) -> "Recorder":
        recorder = self

        async def chat(client, model="", messages=None, **kwargs):
            return await recorder._chat(client, model=model, messages=messages, **kwargs)

        ollama.AsyncClient.chat = chat
        return self

    def uninstall(self) -> None:
        ollama.AsyncClient.chat = self._original

    def _path(self, model: str, key: str) -> Path:
        return self.root / model.replace(":", "_").replace("/", "_") / key[:2] / f"{key}.json"

    async def _chat(self, client, **kwargs) -> ollama.ChatResponse:
        key = request_key(kwargs)
        path = self._path(kwargs["model"], key)
        if self.live:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                response = await self._original(client, **kwargs)
            except asyncio.CancelledError:
                # call_model's deadline cancelled the call. Record that, so a replay times out at the same place
                # (a retry that succeeds overwrites this with the answer).
                path.write_text(json.dumps({"timed_out": True}))
                raise
            path.write_text(response.model_dump_json(exclude_none=True, indent=1))
            self.recorded += 1
        else:
            if not path.exists():
                raise MissingRecording(f"no recorded answer for this request ({path.relative_to(self.root.parent)}); "
                                       "the prompt or code changed since the last live run: run `make eval LIVE=1`")
            recorded = json.loads(path.read_text())
            if recorded.get("timed_out"):
                raise TimeoutError("timed out in the recorded live run")  # call_model turns this into model_timeout
            response = ollama.ChatResponse.model_validate(recorded)
            self.replayed += 1
        self.stats[current_case.get()].append({
            "ms": ((response.total_duration or 0) - (response.load_duration or 0)) / 1e6,
            "prompt_tokens": response.prompt_eval_count or 0, "output_tokens": response.eval_count or 0,
            "output_ms": (response.eval_duration or 0) / 1e6,
        })
        return response
