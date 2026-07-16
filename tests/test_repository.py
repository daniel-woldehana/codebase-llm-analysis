from pathlib import Path

from codebase_analyzer.repository import RepositoryScanner


def test_scanner_filters_build_and_tests(tmp_path: Path) -> None:
    (tmp_path / "src/main").mkdir(parents=True)
    (tmp_path / "src/test").mkdir(parents=True)
    (tmp_path / "build").mkdir()
    (tmp_path / "src/main/App.java").write_text("public class App {}", encoding="utf-8")
    (tmp_path / "src/test/AppTest.java").write_text("public class AppTest {}", encoding="utf-8")
    (tmp_path / "build/Generated.java").write_text("public class Generated {}", encoding="utf-8")

    scan = RepositoryScanner(tmp_path, max_file_bytes=100_000, include_tests=False).scan()
    assert [item.relative_path for item in scan.files] == ["src/main/App.java"]
    assert any("tests excluded" in value for value in scan.skipped)
