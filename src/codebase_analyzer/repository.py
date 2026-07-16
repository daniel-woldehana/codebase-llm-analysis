from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_EXTENSIONS = {
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin Script",
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".jsx": "JavaScript React",
    ".go": "Go",
    ".rs": "Rust",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".xml": "XML",
    ".properties": "Properties",
    ".md": "Markdown",
}

IGNORED_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".vscode",
    ".analysis-cache",
    "node_modules",
    "build",
    "dist",
    "target",
    "out",
    "vendor",
    "coverage",
    "__pycache__",
}

IGNORED_FILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "gradlew",
    "gradlew.bat",
}


@dataclass(frozen=True)
class SourceFile:
    absolute_path: Path
    relative_path: str
    language: str
    content: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ScanResult:
    files: list[SourceFile]
    skipped: list[str]


class RepositoryWorkspace(AbstractContextManager[Path]):
    """Resolve a local directory or clone a Git repository into a temporary workspace."""

    def __init__(
        self,
        repository: str,
        ref: str | None = None,
        keep_clone: bool = False,
        work_dir: Path | None = None,
    ) -> None:
        self.repository = repository
        self.ref = ref
        self.keep_clone = keep_clone
        self.work_dir = work_dir
        self._temp: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None
        self.commit: str | None = None

    @staticmethod
    def _looks_like_remote(value: str) -> bool:
        return value.startswith(("http://", "https://", "git@", "ssh://")) or value.endswith(".git")

    def __enter__(self) -> Path:
        candidate = Path(self.repository).expanduser()
        if candidate.exists():
            self.path = candidate.resolve()
            self.commit = self._read_commit(self.path)
            return self.path

        if not self._looks_like_remote(self.repository):
            raise FileNotFoundError(f"Repository path does not exist: {candidate}")

        if shutil.which("git") is None:
            raise RuntimeError("git is required to clone a remote repository")

        if self.work_dir:
            base = self.work_dir.expanduser().resolve()
            base.mkdir(parents=True, exist_ok=True)
            destination = base / self._safe_name(self.repository)
            if destination.exists():
                shutil.rmtree(destination)
        else:
            self._temp = tempfile.TemporaryDirectory(prefix="codebase-analyzer-")
            destination = Path(self._temp.name) / "repository"

        cmd = ["git", "clone", "--depth", "1"]
        if self.ref:
            cmd += ["--branch", self.ref]
        cmd += [self.repository, str(destination)]
        self._run(cmd)
        self.path = destination
        self.commit = self._read_commit(destination)
        return destination

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._temp and not self.keep_clone:
            self._temp.cleanup()
        return None

    @staticmethod
    def _run(cmd: list[str]) -> str:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Command failed ({' '.join(cmd)}): {message}")
        return completed.stdout.strip()

    @classmethod
    def _read_commit(cls, path: Path) -> str | None:
        if not (path / ".git").exists() or shutil.which("git") is None:
            return None
        try:
            return cls._run(["git", "-C", str(path), "rev-parse", "HEAD"])
        except RuntimeError:
            return None

    @staticmethod
    def _safe_name(url: str) -> str:
        name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name) or "repository"


class RepositoryScanner:
    def __init__(
        self,
        root: Path,
        max_file_bytes: int,
        include_tests: bool = False,
        extensions: dict[str, str] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.include_tests = include_tests
        self.extensions = extensions or DEFAULT_EXTENSIONS

    def scan(self, max_files: int | None = None) -> ScanResult:
        files: list[SourceFile] = []
        skipped: list[str] = []

        for path in self._iter_paths():
            rel = path.relative_to(self.root).as_posix()
            if max_files is not None and len(files) >= max_files:
                skipped.append(f"{rel}: max-files limit reached")
                continue
            if path.name in IGNORED_FILE_NAMES:
                skipped.append(f"{rel}: ignored generated/lock file")
                continue
            language = self.extensions.get(path.suffix.lower())
            if not language:
                continue
            if not self.include_tests and self._is_test_path(path):
                skipped.append(f"{rel}: tests excluded")
                continue
            try:
                size = path.stat().st_size
                if size > self.max_file_bytes:
                    skipped.append(f"{rel}: exceeds {self.max_file_bytes} bytes")
                    continue
                raw = path.read_bytes()
                if b"\x00" in raw:
                    skipped.append(f"{rel}: binary content")
                    continue
                content = raw.decode("utf-8", errors="replace")
            except OSError as exc:
                skipped.append(f"{rel}: read error: {exc}")
                continue

            files.append(
                SourceFile(
                    absolute_path=path,
                    relative_path=rel,
                    language=language,
                    content=content,
                    size_bytes=size,
                    sha256=hashlib.sha256(raw).hexdigest(),
                )
            )

        files.sort(key=lambda item: self._priority(item.relative_path))
        return ScanResult(files=files, skipped=skipped)

    def _iter_paths(self) -> Iterable[Path]:
        for current_root, dirs, names in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
            for name in sorted(names):
                yield Path(current_root) / name

    @staticmethod
    def _is_test_path(path: Path) -> bool:
        lowered = [part.lower() for part in path.parts]
        return "test" in lowered or "tests" in lowered or path.name.lower().endswith("test.java")

    @staticmethod
    def _priority(relative_path: str) -> tuple[int, str]:
        lower = relative_path.lower()
        if lower.endswith(("readme.md", "build.gradle", "build.gradle.kts", "pom.xml", "pyproject.toml")):
            return (0, lower)
        if "/controller/" in lower or lower.endswith("controller.java"):
            return (1, lower)
        if "/service/" in lower or lower.endswith("service.java"):
            return (2, lower)
        if "/repository/" in lower or lower.endswith("repository.java"):
            return (3, lower)
        if "/domain/" in lower or "/model/" in lower or "/entity/" in lower:
            return (4, lower)
        return (5, lower)
