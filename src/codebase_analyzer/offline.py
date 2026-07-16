from __future__ import annotations

from collections import Counter
from .models import FileAnalysis, LLMRepositoryInsight, RepositoryStatistics


class OfflineRepositorySummarizer:
    """Deterministic fallback used for development, CI, and demonstrations without an API key."""

    def summarize(
        self,
        repository_name: str,
        files: list[FileAnalysis],
        statistics: RepositoryStatistics,
    ) -> LLMRepositoryInsight:
        paths = [item.path.lower() for item in files]
        imports = [imp for item in files for imp in item.imports]
        tokens = Counter(part for imp in imports for part in imp.split("."))
        frameworks = self._frameworks(imports, paths)
        controllers = sum(1 for item in files for cls in item.classes if cls.name.endswith("Controller"))
        services = sum(1 for item in files for cls in item.classes if cls.name.endswith(("Service", "ServiceImpl")))
        repositories = sum(1 for item in files for cls in item.classes if cls.name.endswith("Repository"))
        entities = sum(1 for item in files for cls in item.classes if "Entity" in {a.rsplit('.', 1)[-1] for a in cls.annotations})
        endpoints = sum(
            1
            for item in files
            for cls in item.classes
            for method in cls.methods
            if method.endpoint is not None
        )

        is_spring = any("spring" in item for item in imports) or any("build.gradle" in path for path in paths)
        purpose = self._purpose(repository_name, paths, is_spring)
        layers = []
        if controllers:
            layers.append("Web/API layer: annotated controllers expose HTTP operations.")
        if services:
            layers.append("Application/service layer: service classes coordinate business workflows.")
        if repositories:
            layers.append("Persistence layer: repository abstractions access stored data.")
        if entities:
            layers.append("Domain layer: persistence entities model business data.")
        if not layers:
            layers.append("Source modules grouped by directory and responsibility.")

        functionality = []
        if endpoints:
            functionality.append(f"Exposes at least {endpoints} statically detected HTTP endpoint methods.")
        if repositories:
            functionality.append("Reads and writes application data through repository abstractions.")
        if "sakila" in repository_name.lower() or any("sakila" in path for path in paths):
            functionality.append("Provides access to the MySQL Sakila DVD-rental sample domain.")
        if not functionality:
            functionality.append("Implements the behavior represented by the analyzed source files.")

        patterns = []
        if controllers and services and repositories:
            patterns.append("Layered controller-service-repository architecture")
        if any("hateoas" in item.lower() for item in imports):
            patterns.append("HATEOAS resource representation")
        if any("mapstruct" in item.lower() for item in imports):
            patterns.append("Mapper/DTO separation")
        if any("querydsl" in item.lower() for item in imports):
            patterns.append("Type-safe query construction")
        if is_spring:
            patterns.append("Dependency injection and annotation-driven configuration")

        data_flow = []
        if controllers:
            data_flow.append("HTTP request -> controller")
        if services:
            data_flow.append("controller -> application service")
        if repositories:
            data_flow.append("service -> repository/query layer")
        if entities:
            data_flow.append("repository -> relational entity/database")
        if controllers:
            data_flow.append("domain/DTO result -> HTTP response")

        notes = [
            f"Analyzed {statistics.analyzed_files} files and {statistics.method_count} methods.",
            "Cyclomatic complexity is calculated locally rather than estimated by the LLM.",
            "Static parsing and LLM enrichment are intentionally separated for traceability.",
        ]
        if tokens:
            notes.append(f"Frequent imported namespace token: {tokens.most_common(1)[0][0]}.")

        return LLMRepositoryInsight(
            project_name=repository_name,
            purpose=purpose,
            functionality=functionality,
            frameworks_and_libraries=frameworks,
            architecture_style="Layered Spring application" if is_spring else "Modular application",
            architecture_summary=(
                "The repository follows an annotation-driven layered design. Web controllers delegate "
                "to application services, which coordinate persistence through repository/query components. "
                "Cross-cutting configuration and shared utilities are kept in dedicated packages."
                if is_spring
                else "The repository is organized into modules whose responsibilities are inferred from paths and symbols."
            ),
            layers=layers,
            patterns=patterns,
            data_flow=data_flow,
            noteworthy_aspects=notes,
            assumptions=[
                "Descriptions in offline mode are inferred from names, annotations, imports, and directory structure.",
                "Runtime behavior, database state, and external service responses were not executed.",
            ],
            limitations=[
                "Regex-based Java parsing may miss unusual syntax, generated code, or deeply nested declarations.",
                "Offline mode does not provide semantic reasoning equivalent to an LLM run.",
                "Complexity values are static approximations and do not measure cognitive or runtime complexity.",
            ],
        )

    @staticmethod
    def _purpose(repository_name: str, paths: list[str], is_spring: bool) -> str:
        if "sakila" in repository_name.lower():
            return "A Spring-based REST API for accessing and operating on the MySQL Sakila sample database."
        if is_spring:
            return f"A Spring application contained in the {repository_name} repository."
        return f"Software project contained in the {repository_name} repository."

    @staticmethod
    def _frameworks(imports: list[str], paths: list[str]) -> list[str]:
        text = "\n".join(imports + paths).lower()
        candidates = {
            "Spring Boot": ["springframework", "spring-boot"],
            "Spring Data JPA": ["springframework.data.jpa", "spring-data-jpa"],
            "Spring Security": ["springframework.security", "spring-security"],
            "Spring HATEOAS": ["hateoas"],
            "Querydsl": ["querydsl"],
            "MapStruct": ["mapstruct"],
            "Lombok": ["lombok"],
            "Redis": ["redis"],
            "Gradle": ["build.gradle", "gradle/libs"],
            "MySQL": ["mysql"],
        }
        return [name for name, needles in candidates.items() if any(needle in text for needle in needles)]
