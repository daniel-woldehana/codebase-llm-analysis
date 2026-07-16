from pathlib import Path

from codebase_analyzer.java_parser import JavaParser
from codebase_analyzer.repository import SourceFile


def source_file(content: str) -> SourceFile:
    return SourceFile(
        absolute_path=Path("ActorController.java"),
        relative_path="src/main/java/example/ActorController.java",
        language="Java",
        content=content,
        size_bytes=len(content.encode()),
        sha256="abc",
    )


def test_extracts_class_method_endpoint_and_complexity() -> None:
    content = '''
package example;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ActorController {
    @GetMapping("/actors/{id}")
    public String findActor(final Long id) {
        if (id == null || id < 1) {
            throw new IllegalArgumentException();
        }
        return "actor";
    }
}
'''
    analysis = JavaParser().analyze(source_file(content))
    assert analysis.metrics.class_count == 1
    assert analysis.metrics.method_count == 1
    cls = analysis.classes[0]
    assert cls.name == "ActorController"
    method = cls.methods[0]
    assert method.name == "findActor"
    assert method.endpoint is not None
    assert method.endpoint.http_methods == ["GET"]
    assert method.endpoint.paths == ["/actors/{id}"]
    assert method.cyclomatic_complexity == 3  # base + if + ||


def test_ignores_control_statements_as_methods() -> None:
    content = '''
public class Example {
    public void execute() {
        for (int i = 0; i < 3; i++) {
            if (i > 1) { continue; }
        }
    }
}
'''
    analysis = JavaParser().analyze(source_file(content))
    assert [method.name for method in analysis.classes[0].methods] == ["execute"]

