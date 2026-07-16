from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .analyzer import CodebaseAnalyzer
from .config import Settings

app = typer.Typer(
    name="codebase-analyzer",
    help="Analyze a local or remote codebase and produce validated structured JSON.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def analyze(
    repository: Annotated[
        str,
        typer.Option("--repo", "-r", help="Local path or Git repository URL."),
    ] = "https://github.com/codejsha/spring-rest-sakila.git",
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Destination JSON file."),
    ] = Path("output/analysis.json"),
    ref: Annotated[str | None, typer.Option(help="Git branch, tag, or ref to clone.")] = None,
    offline: Annotated[
        bool,
        typer.Option(help="Skip LLM calls and use deterministic descriptions."),
    ] = False,
    include_tests: Annotated[
        bool,
        typer.Option(help="Include test source files in the analysis."),
    ] = False,
    max_files: Annotated[
        int | None,
        typer.Option(min=1, help="Optional total file cap for a fast demonstration."),
    ] = None,
    llm_max_files: Annotated[
        int,
        typer.Option(
            min=1,
            help=(
                "Maximum number of priority-ranked files sent to the LLM. All selected "
                "files still receive deterministic parsing and metrics."
            ),
        ),
    ] = 40,
    progress: Annotated[
        bool,
        typer.Option("--progress/--no-progress", help="Print phase, file, API, retry, and ETA text."),
    ] = True,
    keep_clone: Annotated[
        bool,
        typer.Option(help="Keep a remote clone under --work-dir."),
    ] = False,
    work_dir: Annotated[
        Path | None,
        typer.Option(help="Clone destination base directory."),
    ] = None,
) -> None:
    """Run the complete scan -> parse -> chunk -> LLM -> validate -> JSON pipeline."""

    def emit(message: str) -> None:
        if progress:
            console.print(message, markup=False, highlight=False)

    try:
        settings = Settings()
        report = CodebaseAnalyzer(settings).run(
            repository=repository,
            output=output,
            ref=ref,
            offline=offline,
            include_tests=include_tests,
            max_files=max_files,
            llm_max_files=llm_max_files,
            keep_clone=keep_clone,
            work_dir=work_dir,
            progress=emit,
        )
    except KeyboardInterrupt as exc:
        console.print(
            Panel.fit(
                "Stopped by user. Completed LLM chunk responses remain in .analysis-cache and "
                "will be reused on the next run.",
                title="Analysis stopped",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=130) from exc
    except Exception as exc:
        console.print(Panel.fit(str(exc), title="Analysis failed", border_style="red"))
        raise typer.Exit(code=1) from exc

    table = Table(title="Codebase analysis complete")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Mode", report.execution.mode)
    table.add_row("Files", str(report.statistics.analyzed_files))
    table.add_row("Classes", str(report.statistics.class_count))
    table.add_row("Methods", str(report.statistics.method_count))
    table.add_row("Average complexity", f"{report.statistics.average_method_complexity:.2f}")
    table.add_row("Cache hits", str(report.execution.cache_hits))
    console.print(table)
    console.print(f"[green]JSON written to:[/green] {output.resolve()}")


@app.command("validate-output")
def validate_output(
    path: Annotated[Path, typer.Argument(help="Analysis JSON file to validate.")],
) -> None:
    """Validate an existing JSON artifact against the strict Pydantic schema."""
    from .models import AnalysisReport

    try:
        AnalysisReport.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        console.print(f"[red]Invalid:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Valid analysis report:[/green] {path}")


if __name__ == "__main__":
    app()
