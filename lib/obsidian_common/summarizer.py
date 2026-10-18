"""LLM summarizer: local OpenAI-compatible chat-completions server (LM Studio).

Same shape as embeddings.py - a thin HTTP client, not a library dependency
- but a *different* loaded model on (usually) the same LM Studio instance,
since summarization is chat-completions, not /v1/embeddings. Used by
obsidian_common.raptor.fill_summaries() to replace that module's crude
extractive stand-in with a real generated summary for article/section/
subsection nodes.

The prompt below is adapted from a prior, already-validated RAPTOR pipeline
(old_code/raptor_pipeline/summarizer, conf/prompts/summarize.yaml) - same
instructions (keep key ideas/facts/terms, never invent, match the source
language, be self-contained without the originals), reworded for a single
plain HTTP client instead of LangChain.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import List, Optional

# Matches raptor.py's own heuristic for non-Cyrillic text; the old
# pipeline used 2.5 chars/token specifically tuned for Cyrillic BPE ratios
# (Russian vaults are the primary target here) - see token_utils.py in
# old_code/raptor_pipeline for the source of that number.
CHARS_PER_TOKEN_CYRILLIC = 2.5

DEFAULT_PROMPT_TEMPLATE = """Ты — аналитический ассистент. Прочитай следующие тексты,
которые являются частями одного раздела документа,
и напиши краткое, но содержательное резюме.

Требования:
- Сохрани все ключевые идеи, факты и термины.
- Не выдумывай информацию, которой нет в текстах.
- Пиши на том же языке, на котором написаны тексты.
- Резюме должно быть самодостаточным (понятным без оригиналов).

Тексты:
{text}

Резюме:"""


def estimate_tokens(text: str, chars_per_token: float = CHARS_PER_TOKEN_CYRILLIC) -> int:
    return max(1, math.ceil(len(text) / chars_per_token))


class SummarizerUnavailable(RuntimeError):
    """The chat-completions server is unreachable, refused, timed out, or
    has no model loaded - same operational caveats as
    embeddings.EmbeddingUnavailable (see that module's docstring): LM
    Studio's `lms ps` can say a model is loaded while the HTTP server
    disagrees, and this must degrade explicitly, not hang."""


class LLMSummarizer:
    def __init__(
        self, host: str = "127.0.0.1", port: int = 1234,
        model: str = "gpt-oss-20b-claude-4.5-sonnet-high-reasoning-distill-mlx",
        api_key: str = "", timeout: float = 120.0, temperature: float = 0.3,
        max_tokens: int = 2048, prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    ):
        self.host = host
        self.port = port
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.prompt_template = prompt_template

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
            raise SummarizerUnavailable(
                f"summarizer server at {self.host}:{self.port} returned HTTP {exc.code}: {detail}. "
                "If this says 'no models loaded', load the model from LM Studio's own GUI "
                "(Developer -> Server) - see embeddings.py's module docstring for the same finding."
            ) from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            raise SummarizerUnavailable(
                f"summarizer server not reachable at {self.host}:{self.port} ({exc}). "
                "Is LM Studio running with its local server turned on, and this model loaded?"
            ) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SummarizerUnavailable(f"summarizer server returned non-JSON response: {exc}") from exc

    def summarize(self, texts: List[str]) -> str:
        """One direct chat-completions call - no overflow handling. Use
        `summarize_token_aware` unless the caller already knows the
        combined text is small."""
        if not texts:
            return ""
        combined = "\n---\n".join(texts)
        prompt = self.prompt_template.replace("{text}", combined)
        data = self._post("/v1/chat/completions", {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        })
        choices = data.get("choices")
        if not choices:
            raise SummarizerUnavailable(f"summarizer server returned no 'choices': {data}")
        content = choices[0].get("message", {}).get("content", "")
        return content.strip()

    def summarize_token_aware(
        self, texts: List[str], max_input_tokens: int = 3500,
        chars_per_token: float = CHARS_PER_TOKEN_CYRILLIC,
    ) -> str:
        """Direct summarize() when the combined text fits; otherwise
        divide-and-conquer (old pipeline's "multi_stage": group texts
        under the limit, summarize each group, then recursively summarize
        the resulting summaries) so one oversized node never sends more
        than max_input_tokens worth of text in a single request."""
        if not texts:
            return ""
        combined_tokens = sum(estimate_tokens(t, chars_per_token) for t in texts)
        if combined_tokens <= max_input_tokens:
            return self.summarize(texts)

        groups: List[List[str]] = []
        buf: List[str] = []
        buf_tokens = 0
        for t in texts:
            t_tokens = estimate_tokens(t, chars_per_token)
            if buf and buf_tokens + t_tokens > max_input_tokens:
                groups.append(buf)
                buf, buf_tokens = [], 0
            buf.append(t)
            buf_tokens += t_tokens
        if buf:
            groups.append(buf)

        group_summaries = [self.summarize(g) for g in groups]
        if len(group_summaries) == 1:
            return group_summaries[0]
        # Recurse: the summaries themselves might still overflow the limit
        # if there were many groups - same function, smaller input.
        return self.summarize_token_aware(group_summaries, max_input_tokens, chars_per_token)

    def ping(self) -> bool:
        try:
            self.summarize(["ping"])
            return True
        except SummarizerUnavailable:
            return False
