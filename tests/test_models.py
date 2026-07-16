from datetime import datetime, timezone

from codebase_analyzer.models import (
    AnalysisReport,
    ArchitectureInfo,
    ExecutionInfo,
    ProjectOverview,
    ProjectSource,
    RepositoryStatistics,
)


def test_report_round_trip() -> None:
    report = AnalysisReport(
        generated_at=datetime.now(timezone.utc),
        source=ProjectSource(local_path="/tmp/repo"),
        execution=ExecutionInfo(
            mode="offline",
            provider="deterministic",
            model="offline-rules",
            max_input_tokens=12000,
            reserved_output_tokens=1800,
            analyzed_file_count=0,
            skipped_file_count=0,
        ),
        project=ProjectOverview(name="sample", purpose="test"),
        architecture=ArchitectureInfo(summary="test"),
        statistics=RepositoryStatistics(
            total_files=0,
            analyzed_files=0,
            total_lines=0,
            source_lines=0,
            class_count=0,
            method_count=0,
            aggregate_cyclomatic_complexity=0,
            average_method_complexity=0,
        ),
        files=[],
    )
    assert AnalysisReport.model_validate_json(report.model_dump_json()).project.name == "sample"
