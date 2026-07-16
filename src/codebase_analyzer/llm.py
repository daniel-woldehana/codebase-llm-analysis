from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from .cache import JsonCache
from .config import Settings
from .models import (
    FileAnalysis,
    LLMClassInsight,
    LLMFileInsight,
    LLMRepositoryInsight,
    RepositoryStatistics,
)
from .prompts import (
    FILE_SYSTEM_PROMPT,
    FILE_USER_PROMPT,
    REPOSITORY_SYSTEM_PROMPT,
    REPOSITORY_USER_PROMPT,
)
from .tokenizer import CodeChunk, TokenAwareChunker, TokenCounter

ProgressCallback = Callable[[str], None]


class LLMAnalyzer:
    def __init__(
        self,
        settings: Settings,
        cache: JsonCache,
        progress: ProgressCallback | None = None,
    ) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required unless --offline is used")
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("Install dependencies with: pip install -e .") from exc

        kwargs: dict[str, Any] = {
            "model": settings.llm_model,
            "temperature": settings.llm_temperature,
            "api_key": settings.openai_api_key,
            "max_retries": 0,  # retries are centralized here for predictable behavior
            "timeout": settings.llm_request_timeout_seconds,
        }
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        self.model = ChatOpenAI(**kwargs)
        self.settings = settings
        self.cache = cache
        self.counter = TokenCounter(settings.llm_model)
        self.cache_hits = 0
        self.api_attempts = 0
        self.notify = progress or (lambda _message: None)

    def enrich_file(
        self,
        repository_name: str,
        file_analysis: FileAnalysis,
        source_code: str,
    ) -> FileAnalysis:
        facts = file_analysis.model_dump(
            mode="json",
            exclude={"purpose", "risks", "noteworthy_aspects"},
        )
        facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
        prompt_overhead = self.counter.count(FILE_SYSTEM_PROMPT + FILE_USER_PROMPT + facts_json) + 300
        max_code_tokens = max(500, self.settings.usable_input_tokens - prompt_overhead)
        chunks = TokenAwareChunker(self.counter, max_code_tokens).split(source_code)
        if len(chunks) > 1:
            self.notify(
                f"        Token budget split {file_analysis.path} into {len(chunks)} chunks."
            )
        insights = [
            self._file_chunk(repository_name, file_analysis, facts_json, chunk)
            for chunk in chunks
        ]
        merged = self._merge_file_insights(insights)
        return self._apply(file_analysis, merged)

    def summarize_repository(
        self,
        repository_name: str,
        repository_url: str | None,
        files: list[FileAnalysis],
        statistics: RepositoryStatistics,
    ) -> LLMRepositoryInsight:
        evidence_items = []
        for item in files:
            evidence_items.append(
                {
                    "path": item.path,
                    "language": item.language,
                    "purpose": item.purpose,
                    "classes": [
                        {
                            "name": cls.name,
                            "kind": cls.kind,
                            "description": cls.description,
                            "methods": [
                                {
                                    "name": method.name,
                                    "signature": method.signature,
                                    "description": method.description,
                                    "complexity": method.cyclomatic_complexity,
                                    "endpoint": method.endpoint.model_dump() if method.endpoint else None,
                                }
                                for method in cls.methods
                            ],
                        }
                        for cls in item.classes
                    ],
                    "dependencies": item.dependencies,
                    "risks": item.risks,
                    "noteworthy_aspects": item.noteworthy_aspects,
                }
            )
        languages = sorted({item.language for item in files})
        compact = json.dumps(evidence_items, ensure_ascii=False, separators=(",", ":"))
        budget = max(
            1_000,
            self.settings.usable_input_tokens - self.counter.count(REPOSITORY_USER_PROMPT) - 500,
        )
        compact = self.counter.truncate(compact, budget)
        prompt = REPOSITORY_USER_PROMPT.format(
            repository_name=repository_name,
            repository_url=repository_url or "local repository",
            languages=", ".join(languages),
            statistics_json=statistics.model_dump_json(indent=2),
            file_evidence=compact,
        )
        key = self.cache.key("repository", self.settings.llm_model, prompt)
        cached = self.cache.get(key, LLMRepositoryInsight)
        if cached:
            self.cache_hits += 1
            self.notify("        [cache hit] repository summary")
            return cached
        result = self._invoke_structured(
            LLMRepositoryInsight,
            REPOSITORY_SYSTEM_PROMPT,
            prompt,
            label="repository summary",
        )
        self.cache.put(key, result)
        return result

    def _file_chunk(
        self,
        repository_name: str,
        file_analysis: FileAnalysis,
        facts_json: str,
        chunk: CodeChunk,
    ) -> LLMFileInsight:
        language_hint = {
            "Java": "java",
            "Kotlin": "kotlin",
            "Kotlin Script": "kotlin",
            "Python": "python",
        }.get(file_analysis.language, "text")
        prompt = FILE_USER_PROMPT.format(
            repository_name=repository_name,
            file_path=file_analysis.path,
            language=file_analysis.language,
            chunk_index=chunk.index,
            chunk_total=chunk.total,
            facts_json=facts_json,
            language_hint=language_hint,
            source_code=chunk.content,
        )
        key = self.cache.key(
            "file",
            self.settings.llm_model,
            file_analysis.sha256,
            str(chunk.index),
            prompt,
        )
        cached = self.cache.get(key, LLMFileInsight)
        label = f"{file_analysis.path} chunk {chunk.index + 1}/{chunk.total}"
        if cached:
            self.cache_hits += 1
            self.notify(f"        [cache hit] {label}")
            return cached
        result = self._invoke_structured(
            LLMFileInsight,
            FILE_SYSTEM_PROMPT,
            prompt,
            label=label,
        )
        self.cache.put(key, result)
        return result

    def _invoke_structured(
        self,
        schema: type[Any],
        system_prompt: str,
        user_prompt: str,
        label: str,
    ) -> Any:
        from langchain_core.messages import HumanMessage, SystemMessage
        from tenacity import (
            RetryCallState,
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            wait_exponential,
        )

        structured = self.model.with_structured_output(schema, method="json_schema")
        max_attempts = self.settings.llm_max_retries

        def before_attempt(state: RetryCallState) -> None:
            self.api_attempts += 1
            self.notify(
                f"        [API attempt {state.attempt_number}/{max_attempts}] {label}"
            )

        def before_sleep(state: RetryCallState) -> None:
            error = state.outcome.exception() if state.outcome else None
            delay = state.next_action.sleep if state.next_action else 0.0
            rendered = " ".join(str(error).split()) if error else "unknown error"
            if len(rendered) > 220:
                rendered = rendered[:217] + "..."
            self.notify(
                f"        [retry in {delay:.1f}s] {type(error).__name__}: {rendered}"
            )

        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(Exception),
            before=before_attempt,
            before_sleep=before_sleep,
            reraise=True,
        )
        def invoke() -> Any:
            if self.settings.llm_request_delay_seconds:
                time.sleep(self.settings.llm_request_delay_seconds)
            return structured.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )

        return invoke()

    @staticmethod
    def _merge_file_insights(values: list[LLMFileInsight]) -> LLMFileInsight:
        purpose = next((value.purpose for value in values if value.purpose.strip()), "")
        class_descriptions: dict[str, str] = {}
        method_map: dict[tuple[str, str], Any] = {}
        dependencies: set[str] = set()
        risks: set[str] = set()
        notes: set[str] = set()
        for value in values:
            for item in value.class_insights:
                class_descriptions.setdefault(item.class_name, item.description)
            for method in value.method_insights:
                method_map.setdefault((method.class_name, method.method_name), method)
            dependencies.update(value.dependencies)
            risks.update(value.risks)
            notes.update(value.noteworthy_aspects)
        return LLMFileInsight(
            purpose=purpose,
            class_insights=[
                LLMClassInsight(class_name=name, description=description)
                for name, description in sorted(class_descriptions.items())
            ],
            method_insights=list(method_map.values()),
            dependencies=sorted(dependencies),
            risks=sorted(risks),
            noteworthy_aspects=sorted(notes),
        )

    @staticmethod
    def _apply(file_analysis: FileAnalysis, insight: LLMFileInsight) -> FileAnalysis:
        result = file_analysis.model_copy(deep=True)
        if insight.purpose.strip():
            result.purpose = insight.purpose.strip()
        result.dependencies = sorted(set(result.dependencies) | set(insight.dependencies))
        result.risks = sorted(set(result.risks) | set(insight.risks))
        result.noteworthy_aspects = sorted(
            set(result.noteworthy_aspects) | set(insight.noteworthy_aspects)
        )
        class_map = {item.class_name: item.description for item in insight.class_insights}
        method_map = {
            (item.class_name, item.method_name): item for item in insight.method_insights
        }
        for cls in result.classes:
            if cls.name in class_map:
                cls.description = class_map[cls.name]
            for method in cls.methods:
                item = method_map.get((cls.name, method.name))
                if item:
                    method.description = item.description
                    method.noteworthy_aspects = sorted(
                        set(method.noteworthy_aspects) | set(item.noteworthy_aspects)
                    )
        result.llm_enriched = True
        return result
