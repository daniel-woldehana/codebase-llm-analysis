from codebase_analyzer.tokenizer import TokenAwareChunker, TokenCounter


def test_chunker_respects_budget() -> None:
    counter = TokenCounter("unknown-model")
    text = "\n".join(f"line {index} with several words" for index in range(500))
    chunks = TokenAwareChunker(counter, max_tokens=120, overlap_lines=2).split(text)
    assert len(chunks) > 1
    assert all(chunk.token_count <= 120 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert all(chunk.total == len(chunks) for chunk in chunks)
