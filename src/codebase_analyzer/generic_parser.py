from __future__ import annotations

import re

from .models import FileAnalysis, FileMetrics
from .repository import SourceFile


class GenericParser:
    """Lightweight fallback for non-Java text files."""

    def analyze(self, source: SourceFile) -> FileAnalysis:
        lines = source.content.splitlines()
        blank = sum(1 for line in lines if not line.strip())
        comment = self._comments(lines, source.language)
        source_lines = max(0, len(lines) - blank - comment)
        imports = self._imports(source.content, source.language)
        return FileAnalysis(
            path=source.relative_path,
            language=source.language,
            sha256=source.sha256,
            size_bytes=source.size_bytes,
            purpose=self._purpose(source.relative_path, source.language),
            imports=imports,
            classes=[],
            metrics=FileMetrics(
                lines=len(lines),
                source_lines=source_lines,
                comment_lines=comment,
                blank_lines=blank,
                class_count=0,
                method_count=0,
                aggregate_cyclomatic_complexity=0,
                max_method_complexity=0,
            ),
            dependencies=sorted({item.split(".")[0] for item in imports}),
            risks=[],
            noteworthy_aspects=[],
            llm_enriched=False,
        )

    @staticmethod
    def _comments(lines: list[str], language: str) -> int:
        prefixes = ("#",) if language in {"Python", "YAML", "Properties", "Ruby"} else ("//", "/*", "*")
        return sum(1 for line in lines if line.strip().startswith(prefixes))

    @staticmethod
    def _imports(text: str, language: str) -> list[str]:
        patterns = {
            "Python": r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
            "Kotlin": r"^\s*import\s+([\w.*]+)",
            "Kotlin Script": r"^\s*import\s+([\w.*]+)",
            "JavaScript": r"(?:from\s+['\"]([^'\"]+)|require\(['\"]([^'\"]+))",
            "TypeScript": r"(?:from\s+['\"]([^'\"]+)|require\(['\"]([^'\"]+))",
        }
        pattern = patterns.get(language)
        if not pattern:
            return []
        values: list[str] = []
        for match in re.finditer(pattern, text, re.MULTILINE):
            values.append(next(group for group in match.groups() if group is not None))
        return sorted(set(values))

    @staticmethod
    def _purpose(path: str, language: str) -> str:
        lower = path.lower()
        if lower.endswith("readme.md"):
            return "Project documentation and usage instructions."
        if lower.endswith(("build.gradle.kts", "build.gradle", "pom.xml", "pyproject.toml")):
            return "Build and dependency configuration."
        if lower.endswith(("application.yaml", "application.yml", "application.properties")):
            return "Runtime application configuration."
        return f"{language} source or configuration file."
