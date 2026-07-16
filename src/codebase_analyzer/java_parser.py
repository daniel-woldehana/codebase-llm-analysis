from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ClassInfo, EndpointInfo, FileAnalysis, FileMetrics, MethodInfo, ParameterInfo
from .repository import SourceFile


_CLASS_RE = re.compile(
    r"(?P<annotations>(?:^[ \t]*@[\w.]+(?:\([^\n]*\))?[ \t]*\n)*)"
    r"^[ \t]*(?P<modifiers>(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed)\s+)*)"
    r"(?P<kind>class|interface|enum|record|@interface)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
    r"(?P<tail>[^\{;]*)\{",
    re.MULTILINE,
)

_METHOD_RE = re.compile(
    r"(?P<annotations>(?:^[ \t]*@[\w.]+(?:\([^\n]*(?:\n[^\n]*)*?\))?[ \t]*\n)*)"
    r"^[ \t]*(?P<modifiers>(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp|transient)\s+)*)"
    r"(?:(?P<typeparams><[^;{}=]+>)\s+)?"
    r"(?P<return>[A-Za-z_$][\w$<>\[\],.? @]*(?:\s+extends\s+[\w$<>.?]+)?)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"\((?P<params>[^()]*(?:\([^()]*\)[^()]*)*)\)\s*"
    r"(?:throws\s+(?P<throws>[^\{;]+))?"
    r"(?P<terminator>\{|;)",
    re.MULTILINE,
)

_CONSTRUCTOR_RE = re.compile(
    r"(?P<annotations>(?:^[ \t]*@[\w.]+(?:\([^\n]*\))?[ \t]*\n)*)"
    r"^[ \t]*(?P<modifiers>(?:(?:public|protected|private)\s+)*)"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<params>[^()]*)\)\s*"
    r"(?:throws\s+(?P<throws>[^\{;]+))?(?P<terminator>\{|;)",
    re.MULTILINE,
)

_CONTROL_WORDS = {"if", "for", "while", "switch", "catch", "return", "throw", "new", "do", "else"}
_HTTP_ANNOTATIONS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "PatchMapping": "PATCH",
    "DeleteMapping": "DELETE",
    "RequestMapping": "REQUEST",
}


@dataclass(frozen=True)
class Span:
    start: int
    end: int


class JavaParser:
    def analyze(self, source: SourceFile) -> FileAnalysis:
        text = source.content
        sanitized = self._mask_strings_and_comments(text)
        package = self._first_group(r"\bpackage\s+([\w.]+)\s*;", sanitized)
        imports = re.findall(r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;", sanitized, re.MULTILINE)

        classes: list[ClassInfo] = []
        class_spans: list[tuple[Span, ClassInfo]] = []
        for match in _CLASS_RE.finditer(sanitized):
            body_open = sanitized.find("{", match.start(), match.end() + 1)
            body_close = self._matching_brace(sanitized, body_open) if body_open >= 0 else len(sanitized) - 1
            kind = "annotation" if match.group("kind") == "@interface" else match.group("kind")
            tail = match.group("tail") or ""
            cls = ClassInfo(
                name=match.group("name"),
                kind=kind,  # type: ignore[arg-type]
                package=package,
                modifiers=self._words(match.group("modifiers")),
                annotations=self._annotation_names(match.group("annotations")),
                extends=self._type_list(tail, "extends"),
                implements=self._type_list(tail, "implements"),
                methods=[],
                description=self._describe_class(match.group("name"), kind),
            )
            classes.append(cls)
            class_spans.append((Span(match.start(), body_close + 1), cls))

        for class_span, cls in class_spans:
            cls.methods = self._parse_methods(text, sanitized, class_span, cls.name)

        lines = text.splitlines()
        blank_lines = sum(1 for line in lines if not line.strip())
        comment_lines = self._comment_line_count(text)
        source_lines = max(0, len(lines) - blank_lines - comment_lines)
        methods = [method for cls in classes for method in cls.methods]
        aggregate = sum(method.cyclomatic_complexity for method in methods)
        max_complexity = max((method.cyclomatic_complexity for method in methods), default=0)

        dependencies = sorted(
            {
                imp.split(".")[0]
                for imp in imports
                if not imp.startswith(("java.", "javax."))
            }
        )

        return FileAnalysis(
            path=source.relative_path,
            language=source.language,
            sha256=source.sha256,
            size_bytes=source.size_bytes,
            purpose=self._describe_file(source.relative_path, classes),
            imports=imports,
            classes=classes,
            metrics=FileMetrics(
                lines=len(lines),
                source_lines=source_lines,
                comment_lines=comment_lines,
                blank_lines=blank_lines,
                class_count=len(classes),
                method_count=len(methods),
                aggregate_cyclomatic_complexity=aggregate,
                max_method_complexity=max_complexity,
            ),
            dependencies=dependencies,
            noteworthy_aspects=self._file_noteworthy(classes),
            llm_enriched=False,
        )

    def _parse_methods(
        self,
        original: str,
        sanitized: str,
        class_span: Span,
        class_name: str,
    ) -> list[MethodInfo]:
        methods: list[MethodInfo] = []
        occupied: list[Span] = []
        segment = sanitized[class_span.start : class_span.end]

        for pattern, constructor in ((_METHOD_RE, False), (_CONSTRUCTOR_RE, True)):
            for match in pattern.finditer(segment):
                absolute_start = class_span.start + match.start()
                name = match.group("name")
                if name in _CONTROL_WORDS:
                    continue
                if constructor and name != class_name:
                    continue
                if not constructor and name == class_name:
                    continue
                if any(span.start <= absolute_start < span.end for span in occupied):
                    continue

                terminator_pos = class_span.start + match.end("terminator") - 1
                if match.group("terminator") == "{":
                    end = self._matching_brace(sanitized, terminator_pos)
                else:
                    end = terminator_pos
                if end < terminator_pos:
                    end = terminator_pos

                # Ignore declarations nested inside an already accepted method body.
                if any(span.start < absolute_start < span.end for span in occupied):
                    continue

                occupied.append(Span(absolute_start, end + 1))
                annotation_start = class_span.start + match.start("annotations")
                annotation_end = class_span.start + match.end("annotations")
                annotation_block = original[annotation_start:annotation_end]
                declaration_start = annotation_end
                raw_signature = original[declaration_start:terminator_pos].strip()
                signature = re.sub(r"\s+", " ", raw_signature)
                annotations = self._annotation_names(annotation_block)
                params = self._parameters(match.group("params") or "")
                body = sanitized[terminator_pos : end + 1] if end >= terminator_pos else ""
                start_line = original.count("\n", 0, declaration_start) + 1
                end_line = original.count("\n", 0, end) + 1
                endpoint = self._endpoint(annotation_block)
                return_type = None if constructor else re.sub(r"\s+", " ", match.group("return").strip())

                methods.append(
                    MethodInfo(
                        name=name,
                        signature=signature,
                        return_type=return_type,
                        parameters=params,
                        modifiers=self._words(match.group("modifiers") or ""),
                        annotations=annotations,
                        start_line=start_line,
                        end_line=end_line,
                        lines_of_code=max(1, end_line - start_line + 1),
                        cyclomatic_complexity=self._complexity(body),
                        endpoint=endpoint,
                        description=self._describe_method(name, endpoint, constructor),
                        noteworthy_aspects=self._method_noteworthy(annotations, body),
                    )
                )

        methods.sort(key=lambda item: (item.start_line, item.name))
        return methods

    @staticmethod
    def _matching_brace(text: str, opening: int) -> int:
        if opening < 0 or opening >= len(text) or text[opening] != "{":
            return -1
        depth = 0
        for index in range(opening, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return len(text) - 1

    @staticmethod
    def _mask_strings_and_comments(text: str) -> str:
        result = list(text)
        index = 0
        state = "normal"
        while index < len(text):
            char = text[index]
            nxt = text[index + 1] if index + 1 < len(text) else ""
            if state == "normal":
                if char == "/" and nxt == "/":
                    result[index] = result[index + 1] = " "
                    index += 2
                    state = "line_comment"
                    continue
                if char == "/" and nxt == "*":
                    result[index] = result[index + 1] = " "
                    index += 2
                    state = "block_comment"
                    continue
                if char == '"':
                    result[index] = " "
                    state = "string"
                elif char == "'":
                    result[index] = " "
                    state = "char"
            elif state == "line_comment":
                if char == "\n":
                    state = "normal"
                else:
                    result[index] = " "
            elif state == "block_comment":
                if char == "*" and nxt == "/":
                    result[index] = result[index + 1] = " "
                    index += 2
                    state = "normal"
                    continue
                if char != "\n":
                    result[index] = " "
            elif state in {"string", "char"}:
                quote = '"' if state == "string" else "'"
                if char == "\\":
                    result[index] = " "
                    if index + 1 < len(text):
                        if text[index + 1] != "\n":
                            result[index + 1] = " "
                        index += 2
                        continue
                if char == quote:
                    result[index] = " "
                    state = "normal"
                elif char != "\n":
                    result[index] = " "
            index += 1
        return "".join(result)

    @staticmethod
    def _complexity(body: str) -> int:
        if not body.strip():
            return 1
        decisions = len(
            re.findall(
                r"\bif\b|\bfor\b|\bwhile\b|\bcase\b|\bcatch\b|\?\s*(?![.:])|&&|\|\|",
                body,
            )
        )
        return 1 + decisions

    @staticmethod
    def _parameters(value: str) -> list[ParameterInfo]:
        if not value.strip():
            return []
        parts: list[str] = []
        current: list[str] = []
        depth = 0
        for char in value:
            if char in "<([":
                depth += 1
            elif char in ">)]":
                depth = max(0, depth - 1)
            if char == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            parts.append("".join(current).strip())

        result: list[ParameterInfo] = []
        for part in parts:
            cleaned = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", part)
            cleaned = re.sub(r"\bfinal\s+", "", cleaned).strip()
            match = re.match(r"(.+?)\s+([A-Za-z_$][\w$]*)$", cleaned)
            if match:
                result.append(ParameterInfo(type=match.group(1).strip(), name=match.group(2)))
            else:
                result.append(ParameterInfo(type=cleaned, name="unknown"))
        return result

    @staticmethod
    def _annotation_names(value: str) -> list[str]:
        return re.findall(r"@([\w.]+)", value)

    @staticmethod
    def _endpoint(annotation_block: str) -> EndpointInfo | None:
        methods: list[str] = []
        paths: list[str] = []
        for annotation, http_method in _HTTP_ANNOTATIONS.items():
            for match in re.finditer(rf"@{annotation}\s*(?:\((?P<args>.*?)\))?", annotation_block, re.DOTALL):
                methods.append(http_method)
                args = match.group("args") or ""
                paths.extend(re.findall(r'"([^"\n]+)"', args))
                if annotation == "RequestMapping":
                    declared = re.findall(r"RequestMethod\.([A-Z]+)", args)
                    if declared:
                        methods = [method for method in methods if method != "REQUEST"] + declared
        if not methods:
            return None
        return EndpointInfo(http_methods=sorted(set(methods)), paths=sorted(set(paths)))

    @staticmethod
    def _type_list(tail: str, keyword: str) -> list[str]:
        match = re.search(rf"\b{keyword}\s+(.+?)(?=\bextends\b|\bimplements\b|\bpermits\b|$)", tail)
        if not match:
            return []
        return [part.strip() for part in match.group(1).split(",") if part.strip()]

    @staticmethod
    def _words(value: str) -> list[str]:
        return [word for word in value.split() if word]

    @staticmethod
    def _first_group(pattern: str, text: str) -> str | None:
        match = re.search(pattern, text)
        return match.group(1) if match else None

    @staticmethod
    def _comment_line_count(text: str) -> int:
        count = 0
        in_block = False
        for line in text.splitlines():
            stripped = line.strip()
            if in_block:
                count += 1
                if "*/" in stripped:
                    in_block = False
                continue
            if stripped.startswith("//"):
                count += 1
            elif "/*" in stripped:
                count += 1
                if "*/" not in stripped.split("/*", 1)[1]:
                    in_block = True
        return count

    @staticmethod
    def _split_identifier(name: str) -> str:
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ")
        return spaced.lower()

    def _describe_class(self, name: str, kind: str) -> str:
        human = self._split_identifier(name)
        if name.endswith("Controller"):
            return f"HTTP controller responsible for {human.removesuffix(' controller')} operations."
        if name.endswith("Service") or name.endswith("ServiceImpl"):
            return f"Application service that coordinates {human.replace(' service impl', '').replace(' service', '')} business operations."
        if name.endswith("Repository"):
            return f"Persistence abstraction for {human.removesuffix(' repository')} data."
        if name.endswith(("Entity", "Model")):
            return f"Domain {kind} representing {human.replace(' entity', '').replace(' model', '')}."
        if name.endswith("Config"):
            return f"Configuration {kind} for {human.removesuffix(' config')}."
        return f"Java {kind} representing or supporting {human}."

    def _describe_method(self, name: str, endpoint: EndpointInfo | None, constructor: bool) -> str:
        if constructor:
            return "Constructs and initializes an instance with its required dependencies or state."
        human = self._split_identifier(name)
        if endpoint:
            methods = "/".join(endpoint.http_methods)
            return f"Handles {methods} requests and performs {human}."
        prefixes = {
            "find": "Retrieves",
            "get": "Returns",
            "list": "Lists",
            "create": "Creates",
            "save": "Persists",
            "update": "Updates",
            "delete": "Deletes",
            "remove": "Removes",
            "validate": "Validates",
            "build": "Builds",
            "map": "Maps",
            "convert": "Converts",
            "authenticate": "Authenticates",
            "authorize": "Authorizes",
        }
        for prefix, verb in prefixes.items():
            if name.lower().startswith(prefix):
                remainder = self._split_identifier(name[len(prefix) :]) or "the requested value"
                return f"{verb} {remainder}."
        return f"Implements the {human} operation."

    def _describe_file(self, path: str, classes: list[ClassInfo]) -> str:
        if classes:
            return " Contains ".join(cls.description for cls in classes[:2])
        lower = path.lower()
        if lower.endswith(".gradle.kts"):
            return "Gradle Kotlin build configuration defining plugins, dependencies, and build tasks."
        if lower.endswith((".yaml", ".yml", ".properties")):
            return "Application or infrastructure configuration."
        if lower.endswith("readme.md"):
            return "Project documentation and operating instructions."
        return "Supporting source or configuration file."

    @staticmethod
    def _method_noteworthy(annotations: list[str], body: str) -> list[str]:
        notes: list[str] = []
        simple = {item.rsplit(".", 1)[-1] for item in annotations}
        if simple & set(_HTTP_ANNOTATIONS):
            notes.append("Exposed as an HTTP endpoint.")
        if "Transactional" in simple:
            notes.append("Runs within a transactional boundary.")
        if "Cacheable" in simple or "CacheEvict" in simple or "CachePut" in simple:
            notes.append("Participates in application caching.")
        if re.search(r"\.stream\s*\(", body):
            notes.append("Uses a Java Stream pipeline.")
        if "throw new" in body:
            notes.append("Explicitly creates and throws an exception.")
        return notes

    @staticmethod
    def _file_noteworthy(classes: list[ClassInfo]) -> list[str]:
        notes: list[str] = []
        annotations = {ann.rsplit(".", 1)[-1] for cls in classes for ann in cls.annotations}
        if "RestController" in annotations:
            notes.append("Defines REST API endpoints.")
        if "Entity" in annotations:
            notes.append("Maps a domain type to relational persistence.")
        if "Configuration" in annotations:
            notes.append("Contributes runtime framework configuration.")
        return notes
