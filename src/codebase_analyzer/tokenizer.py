from __future__ import annotations

from dataclasses import dataclass


class TokenCounter:
    def __init__(self, model: str) -> None:
        self.model = model
        self._encoding = None
        try:
            import tiktoken

            try:
                self._encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                self._encoding = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            self._encoding = None

    def count(self, text: str) -> int:
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        # Conservative fallback: code averages fewer than four characters per token.
        return max(1, (len(text) + 2) // 3)

    def truncate(self, text: str, max_tokens: int) -> str:
        if self.count(text) <= max_tokens:
            return text
        if self._encoding is not None:
            tokens = self._encoding.encode(text)[:max_tokens]
            return self._encoding.decode(tokens)
        return text[: max_tokens * 3]


@dataclass(frozen=True)
class CodeChunk:
    index: int
    total: int
    content: str
    token_count: int


class TokenAwareChunker:
    def __init__(self, counter: TokenCounter, max_tokens: int, overlap_lines: int = 8) -> None:
        if max_tokens < 100:
            raise ValueError("max_tokens must be at least 100")
        self.counter = counter
        self.max_tokens = max_tokens
        self.overlap_lines = overlap_lines

    def split(self, text: str) -> list[CodeChunk]:
        if self.counter.count(text) <= self.max_tokens:
            return [CodeChunk(index=1, total=1, content=text, token_count=self.counter.count(text))]

        lines = text.splitlines(keepends=True)
        raw_chunks: list[str] = []
        start = 0
        while start < len(lines):
            low, high = start + 1, len(lines)
            best = start + 1
            while low <= high:
                mid = (low + high) // 2
                candidate = "".join(lines[start:mid])
                if self.counter.count(candidate) <= self.max_tokens:
                    best = mid
                    low = mid + 1
                else:
                    high = mid - 1
            chunk = "".join(lines[start:best])
            if self.counter.count(chunk) > self.max_tokens:
                chunk = self.counter.truncate(chunk, self.max_tokens)
            raw_chunks.append(chunk)
            if best >= len(lines):
                break
            next_start = max(start + 1, best - self.overlap_lines)
            start = next_start

        total = len(raw_chunks)
        return [
            CodeChunk(index=i + 1, total=total, content=value, token_count=self.counter.count(value))
            for i, value in enumerate(raw_chunks)
        ]
