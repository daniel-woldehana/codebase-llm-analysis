from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from .cache import JsonCache
from .config import Settings
from .generic_parser import GenericParser
from .java_parser import JavaParser
from .llm import LLMAnalyzer
from .models import (
    AnalysisReport,
    ArchitectureInfo,
    ExecutionInfo,
    FileAnalysis,
    MethodReference,
    ProjectOverview,
    ProjectSource,
    RepositoryStatistics,
)
from .offline import OfflineRepositorySummarizer
from .repository import RepositoryScanner, RepositoryWorkspace, SourceFile

ProgressCallback = Callable[[str], None]


class CodebaseAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.java_parser = JavaParser()
        self.generic_parser = GenericParser()

    def run(
        self,
        repository: str,
        output: Path,
        ref: str | None = None,
        offline: bool = False,
        include_tests: bool = False,
        max_files: int | None = None,
        llm_max_files: int | None = 40,
        keep_clone: bool = False,
        work_dir: Path | None = None,
        progress: ProgressCallback | None = None,
    ) -> AnalysisReport:
        notify = progress or (lambda _message: None)
        run_started = time.perf_counter()

        notify("[1/6] Preparing repository workspace...")
        with RepositoryWorkspace(
            repository=repository,
            ref=ref,
            keep_clone=keep_clone,
            work_dir=work_dir,
        ) as root:
            workspace = root
            notify(f"[1/6] Repository ready: {workspace}")

            notify("[2/6] Scanning eligible source and documentation files...")
            scanner = RepositoryScanner(
                root=workspace,
                max_file_bytes=self.settings.max_file_bytes,
                include_tests=include_tests,
            )
            scan = scanner.scan(max_files=max_files)
            notify(
                f"[2/6] Scan complete: {len(scan.files)} files selected; "
                f"{len(scan.skipped)} skipped."
            )

            notify("[3/6] Running deterministic parsing and complexity analysis...")
            analyses: list[FileAnalysis] = []
            total_static = len(scan.files)
            for index, source in enumerate(scan.files, start=1):
                notify(f"    [static {index}/{total_static}] {source.relative_path}")
                analyses.append(self._parse(source))
            notify(f"[3/6] Static analysis complete for {len(analyses)} files.")

            repository_name = self._repository_name(repository, workspace)
            cache = JsonCache(self.settings.cache_dir)
            cache_hits = 0
            warnings: list[str] = []

            if offline:
                notify("[4/6] Offline mode enabled; skipping external LLM calls.")
                enriched = analyses
                repo_insight = OfflineRepositorySummarizer().summarize(
                    repository_name,
                    enriched,
                    self._statistics(enriched, len(scan.files)),
                )
                provider = "deterministic"
                model = "offline-rules"
            else:
                llm = LLMAnalyzer(self.settings, cache, progress=notify)
                enriched: list[FileAnalysis] = []
                source_by_path = {source.relative_path: source for source in scan.files}

                requested_llm_files = len(analyses)
                if llm_max_files is not None:
                    requested_llm_files = min(llm_max_files, len(analyses))
                llm_targets = {item.path for item in analyses[:requested_llm_files]}

                if requested_llm_files < len(analyses):
                    warning = (
                        f"LLM enrichment limited to {requested_llm_files} priority-ranked files; "
                        f"the remaining {len(analyses) - requested_llm_files} files retain complete "
                        "deterministic static analysis."
                    )
                    warnings.append(warning)
                    notify(f"[4/6] {warning}")
                else:
                    notify(f"[4/6] LLM enrichment scheduled for all {requested_llm_files} files.")

                llm_completed = 0
                llm_started = time.perf_counter()
                for item in analyses:
                    if item.path not in llm_targets:
                        enriched.append(item)
                        continue

                    llm_completed += 1
                    source = source_by_path[item.path]
                    item_started = time.perf_counter()
                    notify(f"    [LLM {llm_completed}/{requested_llm_files}] START {item.path}")
                    try:
                        enriched_item = llm.enrich_file(
                            repository_name,
                            item,
                            source.content,
                        )
                        enriched.append(enriched_item)
                        elapsed = time.perf_counter() - item_started
                        average = (time.perf_counter() - llm_started) / llm_completed
                        remaining = requested_llm_files - llm_completed
                        eta = average * remaining
                        notify(
                            f"    [LLM {llm_completed}/{requested_llm_files}] DONE  {item.path} "
                            f"({format_duration(elapsed)}; ETA {format_duration(eta)})"
                        )
                    except Exception as exc:  # one failed file should not destroy the full report
                        elapsed = time.perf_counter() - item_started
                        message = f"LLM enrichment failed for {item.path}: {exc}"
                        warnings.append(message)
                        enriched.append(item)
                        notify(
                            f"    [LLM {llm_completed}/{requested_llm_files}] FAILED {item.path} "
                            f"after {format_duration(elapsed)}: {short_error(exc)}"
                        )

                stats = self._statistics(enriched, len(scan.files))
                notify("[5/6] Generating repository-level architecture summary...")
                summary_started = time.perf_counter()
                repo_insight = llm.summarize_repository(
                    repository_name,
                    repository if self._looks_remote(repository) else None,
                    enriched,
                    stats,
                )
                notify(
                    "[5/6] Repository summary complete "
                    f"in {format_duration(time.perf_counter() - summary_started)}."
                )
                cache_hits = llm.cache_hits
                provider = "OpenAI-compatible via LangChain"
                model = self.settings.llm_model

            statistics = self._statistics(enriched, len(scan.files))
            key_methods = self._key_methods(enriched)
            hotspots = sorted(
                key_methods,
                key=lambda item: (-item.cyclomatic_complexity, item.file),
            )[:15]
            languages = sorted({item.language for item in enriched})
            report = AnalysisReport(
                source=ProjectSource(
                    repository_url=repository if self._looks_remote(repository) else None,
                    local_path=None if self._looks_remote(repository) else str(workspace),
                    branch_or_ref=ref,
                    commit=self._commit(workspace),
                ),
                execution=ExecutionInfo(
                    mode="offline" if offline else "llm",
                    provider=provider,
                    model=model,
                    max_input_tokens=self.settings.max_input_tokens,
                    reserved_output_tokens=self.settings.reserved_output_tokens,
                    analyzed_file_count=len(enriched),
                    skipped_file_count=len(scan.skipped),
                    cache_hits=cache_hits,
                    warnings=warnings + scan.skipped[:100],
                ),
                project=ProjectOverview(
                    name=repo_insight.project_name,
                    purpose=repo_insight.purpose,
                    functionality=repo_insight.functionality,
                    languages=languages,
                    frameworks_and_libraries=repo_insight.frameworks_and_libraries,
                    architecture_style=repo_insight.architecture_style,
                ),
                architecture=ArchitectureInfo(
                    summary=repo_insight.architecture_summary,
                    layers=repo_insight.layers,
                    patterns=repo_insight.patterns,
                    data_flow=repo_insight.data_flow,
                ),
                statistics=statistics,
                files=enriched,
                key_methods=key_methods[:30],
                complexity_hotspots=hotspots,
                noteworthy_aspects=repo_insight.noteworthy_aspects,
                assumptions=repo_insight.assumptions,
                limitations=repo_insight.limitations,
            )
            notify(f"[6/6] Validating and writing JSON to {output}...")
            self._write(output, report)
            notify(
                f"[6/6] Finished successfully in "
                f"{format_duration(time.perf_counter() - run_started)}."
            )
            return report

    def _parse(self, source: SourceFile) -> FileAnalysis:
        if source.language == "Java":
            return self.java_parser.analyze(source)
        return self.generic_parser.analyze(source)

    @staticmethod
    def _statistics(files: list[FileAnalysis], total_files: int) -> RepositoryStatistics:
        method_count = sum(item.metrics.method_count for item in files)
        complexity = sum(item.metrics.aggregate_cyclomatic_complexity for item in files)
        return RepositoryStatistics(
            total_files=total_files,
            analyzed_files=len(files),
            total_lines=sum(item.metrics.lines for item in files),
            source_lines=sum(item.metrics.source_lines for item in files),
            class_count=sum(item.metrics.class_count for item in files),
            method_count=method_count,
            aggregate_cyclomatic_complexity=complexity,
            average_method_complexity=round(complexity / method_count, 2) if method_count else 0.0,
        )

    @staticmethod
    def _key_methods(files: list[FileAnalysis]) -> list[MethodReference]:
        values: list[MethodReference] = []
        for file in files:
            for cls in file.classes:
                for method in cls.methods:
                    values.append(
                        MethodReference(
                            file=file.path,
                            class_name=cls.name,
                            name=method.name,
                            signature=method.signature,
                            cyclomatic_complexity=method.cyclomatic_complexity,
                            description=method.description,
                        )
                    )
        return sorted(values, key=lambda item: (-self_score(item, files), item.file, item.name))

    @staticmethod
    def _write(path: Path, report: AnalysisReport) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        AnalysisReport.model_validate_json(temporary.read_text(encoding="utf-8"))
        temporary.replace(path)

    @staticmethod
    def _repository_name(repository: str, workspace: Path) -> str:
        if CodebaseAnalyzer._looks_remote(repository):
            return repository.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        return workspace.name

    @staticmethod
    def _looks_remote(value: str) -> bool:
        return value.startswith(("http://", "https://", "git@", "ssh://")) or value.endswith(".git")

    @staticmethod
    def _commit(workspace: Path) -> str | None:
        head = workspace / ".git" / "HEAD"
        if not head.exists():
            return None
        try:
            import subprocess

            result = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except OSError:
            return None


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def short_error(exc: Exception, limit: int = 220) -> str:
    value = " ".join(str(exc).split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def self_score(method: MethodReference, files: list[FileAnalysis]) -> int:
    score = method.cyclomatic_complexity
    for file in files:
        if file.path != method.file:
            continue
        for cls in file.classes:
            if cls.name != method.class_name:
                continue
            for candidate in cls.methods:
                if candidate.name == method.name and candidate.signature == method.signature:
                    if candidate.endpoint:
                        score += 5
                    if candidate.annotations:
                        score += 1
                    if candidate.noteworthy_aspects:
                        score += 1
                    return score
    return score
