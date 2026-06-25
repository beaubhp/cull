#!/usr/bin/env python3
"""Run Cull's public benchmark suite.

The benchmark is intentionally dependency-free. Projects and expected findings
are checked in; the runner only validates, executes tools, parses outputs, and
scores deterministic results.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CATEGORIES = {
    "unused_import",
    "unused_local",
    "unreachable_statement",
    "unused_function",
    "unused_class",
    "unused_private_method",
}

CULL_TYPE_TO_CATEGORY = {
    ("CULL001", "function"): "unused_function",
    ("CULL002", "class"): "unused_class",
    ("CULL003", "function"): "unused_function",
    ("CULL004", "class"): "unused_class",
    ("CULL005", None): "unused_import",
    ("CULL006", None): "unused_local",
    ("CULL007", None): "unreachable_statement",
    ("CULL008", "function"): "unused_private_method",
}

VULTURE_RE = re.compile(
    r"^(?P<path>.*?):(?P<line>\d+): unused "
    r"(?P<kind>function|class|method|import|variable|attribute|property) "
    r"'(?P<name>[^']+)'"
)
VULTURE_UNREACHABLE_RE = re.compile(r"^(?P<path>.*?):(?P<line>\d+): unreachable code")
DEADCODE_RE = re.compile(
    r"^(?P<path>.*?):(?P<line>\d+):(?P<column>\d+): "
    r"(?P<code>DC\d+) (?P<kind>Function|Class|Method|Variable|Import|Name|Attribute|Property) "
    r"`(?P<name>[^`]+)` is never used"
)
DEADCODE_UNREACHABLE_RE = re.compile(
    r"^(?P<path>.*?):(?P<line>\d+):(?P<column>\d+): (?P<code>DC\d+) .*unreachable"
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
NORMAL_EXIT_CODES = {
    "cull": {0, 1},
    "vulture": {0, 3},
    "deadcode": {0},
}


@dataclass(frozen=True)
class ExpectedFinding:
    id: str
    category: str
    path: str
    name: str | None
    line: int
    column: int | None
    end_line: int
    rationale: str
    qualified_name: str | None = None
    end_column: int | None = None
    cull_rule: str | None = None
    tool_notes: str | None = None


@dataclass(frozen=True)
class ToolFinding:
    tool: str
    category: str
    path: str
    line: int
    name: str | None
    raw: str
    rule_id: str | None = None
    confidence: str | None = None


@dataclass
class CommandRun:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    max_rss_bytes: int | None
    timed_out: bool = False


@dataclass
class Project:
    id: str
    path: Path
    expected_path: Path
    mode: str
    source_roots: list[str]
    shape: str
    clean: bool = False
    large: bool = False


@dataclass
class ProjectResult:
    project: Project
    expected: list[ExpectedFinding]
    tool_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    cull_high_plus_review: dict[str, Any] | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="suite.json")
    parser.add_argument("--cull", default="target/release/cull")
    parser.add_argument("--tools", default="cull,vulture,deadcode")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--results", default="benchmark/results/latest.json")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--project", action="append", dest="projects")
    args = parser.parse_args()

    benchmark_root = Path(__file__).resolve().parent
    repo_root = benchmark_root.parent
    suite = load_json(benchmark_root / args.suite)
    validate_suite_schema(suite)
    all_projects = load_projects(benchmark_root, suite)
    expected_by_project = {
        project.id: load_expected(project.expected_path) for project in all_projects
    }
    corpus = validate_corpus(all_projects, expected_by_project)
    projects = all_projects
    if args.projects:
        selected = set(args.projects)
        projects = [project for project in projects if project.id in selected]
        missing = selected - {project.id for project in projects}
        if missing:
            raise SystemExit(f"unknown project selection: {', '.join(sorted(missing))}")
    if args.validate_only:
        print(
            "benchmark corpus is valid: "
            f"{corpus['project_count']} projects, "
            f"{corpus['python_files']} Python files, "
            f"{corpus['python_loc']} Python LOC, "
            f"{corpus['expected_findings']} expected findings"
        )
        return 0

    tools = parse_tools(args.tools)
    validate_runtime_args(args, tools, repo_root)
    result = run_benchmark(
        benchmark_root=benchmark_root,
        repo_root=repo_root,
        suite=suite,
        projects=projects,
        expected_by_project=expected_by_project,
        corpus=corpus,
        tools=tools,
        cull=(repo_root / args.cull).resolve(),
        runs=args.runs,
        warmups=args.warmups,
        timeout=args.timeout,
    )
    result = normalize_paths(result, repo_root)
    result_path = resolve_result_path(repo_root, benchmark_root, args.results)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(result_path, result)
    write_markdown(result_path.with_suffix(".md"), result)
    print(f"wrote {result_path}")
    print(
        "aggregate: "
        + ", ".join(
            f"{tool} precision={metrics['precision']:.3f} "
            f"recall={metrics['recall']:.3f} f1={metrics['f1']:.3f}"
            for tool, metrics in result["aggregate"].items()
        )
    )
    return 0


def parse_tools(value: str) -> list[str]:
    tools = [tool.strip() for tool in value.split(",") if tool.strip()]
    allowed = {"cull", "vulture", "deadcode"}
    unknown = set(tools) - allowed
    if unknown:
        raise SystemExit(f"unknown benchmark tools: {', '.join(sorted(unknown))}")
    if not tools:
        raise SystemExit("at least one tool must be selected")
    return tools


def validate_suite_schema(suite: dict[str, Any]) -> None:
    if not isinstance(suite, dict):
        raise SystemExit("benchmark suite must be a JSON object")
    if suite.get("schema_version") != 1:
        raise SystemExit("benchmark suite schema_version must be 1")
    if not isinstance(suite.get("projects"), list):
        raise SystemExit("benchmark suite projects must be a list")


def validate_runtime_args(args: argparse.Namespace, tools: list[str], repo_root: Path) -> None:
    if args.runs <= 0:
        raise SystemExit("--runs must be positive")
    if args.warmups < 0:
        raise SystemExit("--warmups must be non-negative")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    if "cull" in tools and not (repo_root / args.cull).exists():
        raise SystemExit(f"Cull binary not found: {repo_root / args.cull}")
    if any(tool in tools for tool in ("vulture", "deadcode")) and shutil.which("uvx") is None:
        raise SystemExit("uvx is required to run Vulture/deadcode baselines")


def resolve_result_path(repo_root: Path, benchmark_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "benchmark":
        return repo_root / path
    return benchmark_root / path


def load_projects(benchmark_root: Path, suite: dict[str, Any]) -> list[Project]:
    projects = []
    for index, entry in enumerate(suite.get("projects", [])):
        if not isinstance(entry, dict):
            raise SystemExit(f"suite.projects[{index}] must be an object")
        project_id = require_string(entry, "id", f"suite.projects[{index}]")
        projects.append(
            Project(
                id=project_id,
                path=benchmark_root / require_string(entry, "path", project_id),
                expected_path=benchmark_root / require_string(entry, "expected", project_id),
                mode=require_string(entry, "mode", project_id),
                source_roots=require_string_list(
                    entry.get("source_roots", ["src"]),
                    "source_roots",
                    project_id,
                ),
                shape=require_string(entry, "shape", project_id),
                clean=optional_bool(entry.get("clean", False), "clean", project_id),
                large=optional_bool(entry.get("large", False), "large", project_id),
            )
        )
    return projects


def load_expected(path: Path) -> list[ExpectedFinding]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected file must be a JSON object")
    items = data.get("expected")
    if not isinstance(items, list):
        raise SystemExit(f"{path}: expected must be a list")
    expected = []
    for index, item in enumerate(items):
        context = f"{path}:{index}"
        if not isinstance(item, dict):
            raise SystemExit(f"{context}: expected item must be an object")
        category = require_string(item, "category", context)
        if category not in CATEGORIES:
            raise SystemExit(f"{context}: invalid category {category!r}")
        line = require_int(item, "line", context)
        end_line = int(item.get("end_line", line))
        if end_line < line:
            raise SystemExit(f"{context}: end_line must be >= line")
        column = optional_int(item.get("column"), "column", context)
        expected.append(
            ExpectedFinding(
                id=require_string(item, "id", context),
                category=category,
                path=normalize_relative_path(require_string(item, "path", context)),
                name=optional_string(item.get("name"), "name", context),
                line=line,
                column=column,
                end_line=end_line,
                rationale=require_string(item, "rationale", context),
                qualified_name=optional_string(
                    item.get("qualified_name"), "qualified_name", context
                ),
                end_column=optional_int(item.get("end_column"), "end_column", context),
                cull_rule=optional_string(item.get("cull_rule"), "cull_rule", context),
                tool_notes=optional_string(item.get("tool_notes"), "tool_notes", context),
            )
        )
    return expected


def validate_corpus(
    projects: list[Project],
    expected_by_project: dict[str, list[ExpectedFinding]],
    *,
    enforce_size: bool = True,
) -> dict[str, Any]:
    if enforce_size and len(projects) != 15:
        raise SystemExit(f"benchmark must contain 15 projects, found {len(projects)}")

    project_ids = [project.id for project in projects]
    duplicate_projects = duplicates(project_ids)
    if duplicate_projects:
        raise SystemExit(f"duplicate project ids: {', '.join(duplicate_projects)}")

    all_expected_ids: list[str] = []
    expected_count = 0
    category_counts = {category: 0 for category in sorted(CATEGORIES)}
    python_files = 0
    python_loc = 0
    clean_projects = 0
    large_projects = 0
    answer_token_hits: list[str] = []

    for project in projects:
        if not project.path.exists():
            raise SystemExit(f"{project.id}: project path does not exist: {project.path}")
        if not project.expected_path.exists():
            raise SystemExit(
                f"{project.id}: expected file does not exist: {project.expected_path}"
            )
        validate_expected_metadata(project)
        if project.mode not in {"auto", "application", "library"}:
            raise SystemExit(f"{project.id}: invalid mode {project.mode!r}")
        for source_root in project.source_roots:
            if not (project.path / source_root).exists():
                raise SystemExit(f"{project.id}: missing source root {source_root!r}")

        files = sorted(project.path.rglob("*.py"))
        if not files:
            raise SystemExit(f"{project.id}: no Python files")
        project_loc = 0
        for file_path in files:
            text = file_path.read_text(encoding="utf-8")
            project_loc += count_loc(text)
            if contains_answer_leak(text):
                answer_token_hits.append(os.fspath(file_path))
        python_files += len(files)
        python_loc += project_loc

        expected = expected_by_project[project.id]
        if project.clean and expected:
            raise SystemExit(f"{project.id}: clean project has expected findings")
        if project.clean:
            clean_projects += 1
        if project.large:
            large_projects += 1
        expected_count += len(expected)
        all_expected_ids.extend(finding.id for finding in expected)
        for finding in expected:
            category_counts[finding.category] += 1
            target = project.path / finding.path
            if not target.exists():
                raise SystemExit(f"{project.id}: expected path missing: {finding.path}")
            if not finding.rationale.strip():
                raise SystemExit(f"{project.id}: empty rationale for {finding.id}")

    duplicate_ids = duplicates(all_expected_ids)
    if duplicate_ids:
        raise SystemExit(f"duplicate expected ids: {', '.join(duplicate_ids[:10])}")
    if answer_token_hits:
        raise SystemExit(
            "benchmark source files contain answer-leaking comments/tokens: "
            + ", ".join(answer_token_hits[:10])
        )
    if enforce_size and not (45_000 <= python_loc <= 80_000):
        raise SystemExit(f"total Python LOC must be 45k-80k, found {python_loc}")
    if enforce_size and not (250 <= python_files <= 500):
        raise SystemExit(f"Python file count must be 250-500, found {python_files}")
    if enforce_size and not (500 <= expected_count <= 900):
        raise SystemExit(
            f"expected finding count must be 500-900, found {expected_count}"
        )
    if enforce_size and clean_projects != 2:
        raise SystemExit(f"benchmark must contain 2 clean projects, found {clean_projects}")
    if enforce_size and large_projects < 2:
        raise SystemExit(
            f"benchmark must contain at least 2 large/noisy projects, found {large_projects}"
        )
    missing_categories = [category for category, count in category_counts.items() if count == 0]
    if enforce_size and missing_categories:
        raise SystemExit(f"missing expected categories: {', '.join(missing_categories)}")

    return {
        "project_count": len(projects),
        "python_files": python_files,
        "python_loc": python_loc,
        "expected_findings": expected_count,
        "clean_projects": clean_projects,
        "large_projects": large_projects,
        "category_counts": category_counts,
    }


def validate_expected_metadata(project: Project) -> None:
    data = load_json(project.expected_path)
    if not isinstance(data, dict):
        raise SystemExit(f"{project.id}: expected file must be a JSON object")
    expected_project = require_string(data, "project", os.fspath(project.expected_path))
    if expected_project != project.id:
        raise SystemExit(
            f"{project.id}: expected project metadata is {expected_project!r}"
        )
    benchmark_root = project.expected_path.parent.parent
    try:
        expected_root = normalize_relative_path(
            os.fspath(project.path.relative_to(benchmark_root))
        )
    except ValueError:
        raise SystemExit(
            f"{project.id}: project path must be under benchmark root"
        ) from None
    actual_root = normalize_relative_path(
        require_string(data, "root", os.fspath(project.expected_path))
    )
    if actual_root != expected_root:
        raise SystemExit(
            f"{project.id}: expected root metadata is {actual_root!r}, "
            f"expected {expected_root!r}"
        )


def contains_answer_leak(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip().lower()
        if not stripped.startswith("#"):
            continue
        if any(token in stripped for token in ("dead", "unused", "expected", "benchmark")):
            return True
    return False


def run_benchmark(
    *,
    benchmark_root: Path,
    repo_root: Path,
    suite: dict[str, Any],
    projects: list[Project],
    expected_by_project: dict[str, list[ExpectedFinding]],
    corpus: dict[str, Any],
    tools: list[str],
    cull: Path,
    runs: int,
    warmups: int,
    timeout: float,
) -> dict[str, Any]:
    raw_root = benchmark_root / "results" / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    tool_metadata = collect_tool_metadata(repo_root, cull, tools)
    project_results = []

    for project in projects:
        expected = expected_by_project[project.id]
        result = ProjectResult(project=project, expected=expected)
        for tool in tools:
            run_result = run_tool_project(
                tool=tool,
                project=project,
                cull=cull,
                runs=runs,
                warmups=warmups,
                timeout=timeout,
            )
            raw_path = write_raw_output(raw_root, tool, project.id, run_result["last_run"])
            findings = parse_tool_findings(
                tool,
                run_result["last_run"].stdout,
                project.path,
                include_cull_review=False,
            )
            parse_warnings = collect_parse_warnings(
                tool,
                run_result["last_run"].stdout,
            )
            validate_parse_warnings(tool, project, parse_warnings)
            metrics = score_findings(expected, findings)
            result.tool_results[tool] = {
                "command": run_result["command"],
                "version": tool_metadata[tool]["version"],
                "runs": [serialize_run(run) for run in run_result["measured_runs"]],
                "median_seconds": median([run.seconds for run in run_result["measured_runs"]]),
                "max_rss_bytes": max_rss(run_result["measured_runs"]),
                "raw_output": os.fspath(raw_path),
                "finding_count": len(findings),
                "parse_warnings": parse_warnings,
                "metrics": metrics,
            }
            if tool == "cull":
                review_findings = parse_tool_findings(
                    tool,
                    run_result["last_run"].stdout,
                    project.path,
                    include_cull_review=True,
                )
                result.cull_high_plus_review = {
                    "finding_count": len(review_findings),
                    "metrics": score_findings(expected, review_findings),
                }
        project_results.append(result)

    result = {
        "schema_version": 1,
        "suite": suite.get("description", "Cull benchmark"),
        "corpus": corpus,
        "environment": environment(repo_root, runs, warmups, timeout),
        "tools": tool_metadata,
        "aggregate": aggregate(project_results, tools),
        "by_category": aggregate_by_category(project_results, tools),
        "timing": timing_summary(project_results, tools),
        "projects": [serialize_project_result(result, tools) for result in project_results],
    }
    if "cull" in tools:
        result["cull_high_plus_review"] = aggregate_cull_review(project_results)
    return result


def run_tool_project(
    *,
    tool: str,
    project: Project,
    cull: Path,
    runs: int,
    warmups: int,
    timeout: float,
) -> dict[str, Any]:
    command = command_for_tool(tool, project, cull)
    for _ in range(warmups):
        validate_command_run(tool, project, run_command(command, timeout))
    measured = []
    for _ in range(runs):
        run = run_command(command, timeout)
        validate_command_run(tool, project, run)
        measured.append(run)
    last = measured[-1]
    return {"command": command, "measured_runs": measured, "last_run": last}


def command_for_tool(tool: str, project: Project, cull: Path) -> list[str]:
    source_roots = [os.fspath(project.path / source) for source in project.source_roots]
    if tool == "cull":
        command = [
            os.fspath(cull),
            "check",
            os.fspath(project.path),
            "--format",
            "json",
            "--mode",
            project.mode,
        ]
        for source in project.source_roots:
            command.extend(["--src", source])
        return command
    if tool == "vulture":
        return ["uvx", "vulture==2.16", *source_roots]
    if tool == "deadcode":
        return ["uvx", "--python", "3.11", "deadcode==2.4.1", *source_roots]
    raise ValueError(tool)


def validate_command_run(tool: str, project: Project, run: CommandRun) -> None:
    if run.timed_out:
        raise SystemExit(f"{tool} timed out on {project.id}")
    accepted = NORMAL_EXIT_CODES.get(tool)
    if accepted is None:
        raise ValueError(tool)
    if run.exit_code not in accepted:
        raise SystemExit(
            f"{tool} failed on {project.id} with exit code {run.exit_code}: "
            f"{stderr_summary(run.stderr)}"
        )
    if run.stderr.strip():
        raise SystemExit(f"{tool} wrote stderr on {project.id}: {stderr_summary(run.stderr)}")


def validate_parse_warnings(tool: str, project: Project, warnings: list[str]) -> None:
    if warnings:
        raise SystemExit(
            f"{tool} output could not be fully parsed on {project.id}: "
            + "; ".join(warnings[:3])
        )


def stderr_summary(stderr: str) -> str:
    text = " ".join(line.strip() for line in stderr.splitlines() if line.strip())
    if not text:
        return "no stderr"
    if len(text) > 300:
        return f"{text[:297]}..."
    return text


def run_command(command: list[str], timeout: float) -> CommandRun:
    timed_command = time_command(command)
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            timed_command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
        seconds = time.perf_counter() - start
        stderr, max_rss = split_time_stderr(completed.stderr)
        return CommandRun(
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=stderr,
            seconds=seconds,
            max_rss_bytes=max_rss,
        )
    except subprocess.TimeoutExpired as error:
        return CommandRun(
            command=command,
            exit_code=124,
            stdout=error.stdout or "",
            stderr=error.stderr or "",
            seconds=time.perf_counter() - start,
            max_rss_bytes=None,
            timed_out=True,
        )


def time_command(command: list[str]) -> list[str]:
    if Path("/usr/bin/time").exists():
        return ["/usr/bin/time", "-l", *command]
    return command


def split_time_stderr(stderr: str) -> tuple[str, int | None]:
    max_rss = None
    tool_lines = []
    for line in stderr.splitlines():
        stripped = line.strip()
        if stripped.endswith("maximum resident set size"):
            try:
                max_rss = int(stripped.split()[0])
            except (IndexError, ValueError):
                max_rss = None
            continue
        if stripped.startswith("Command being timed:"):
            continue
        if re.match(r"^\d+\.\d+ real\s+\d+\.\d+ user\s+\d+\.\d+ sys$", stripped):
            continue
        if any(
            stripped.endswith(suffix)
            for suffix in (
                "average shared memory size",
                "average unshared data size",
                "average unshared stack size",
                "page reclaims",
                "page faults",
                "swaps",
                "block input operations",
                "block output operations",
                "messages sent",
                "messages received",
                "signals received",
                "voluntary context switches",
                "involuntary context switches",
                "instructions retired",
                "cycles elapsed",
                "peak memory footprint",
            )
        ):
            continue
        tool_lines.append(line)
    return "\n".join(tool_lines), max_rss


def parse_tool_findings(
    tool: str,
    stdout: str,
    project_root: Path,
    *,
    include_cull_review: bool,
) -> list[ToolFinding]:
    if tool == "cull":
        return parse_cull(stdout, include_review=include_cull_review)
    if tool == "vulture":
        return parse_vulture(stdout, project_root)
    if tool == "deadcode":
        return parse_deadcode(stdout, project_root)
    raise ValueError(tool)


def parse_cull(stdout: str, *, include_review: bool = False) -> list[ToolFinding]:
    if not stdout.strip():
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    findings = []
    for item in data.get("findings", []):
        confidence = item.get("confidence")
        if confidence != "high" and not (include_review and confidence == "review"):
            continue
        subject = item.get("subject", {})
        rule_id = item.get("rule_id")
        category = cull_category(rule_id, subject)
        if category is None:
            continue
        path, line, name = subject_location(subject, category)
        findings.append(
            ToolFinding(
                tool="cull",
                category=category,
                path=path,
                line=line,
                name=name,
                raw=item.get("finding_id", ""),
                rule_id=rule_id,
                confidence=confidence,
            )
        )
    return findings


def cull_category(rule_id: str | None, subject: dict[str, Any]) -> str | None:
    subject_kind = None
    if subject.get("subject_type") == "definition":
        subject_kind = subject.get("kind")
    return CULL_TYPE_TO_CATEGORY.get((rule_id, subject_kind)) or CULL_TYPE_TO_CATEGORY.get(
        (rule_id, None)
    )


def subject_location(subject: dict[str, Any], category: str) -> tuple[str, int, str | None]:
    subject_type = subject.get("subject_type")
    if subject_type == "import_binding":
        return (
            normalize_relative_path(subject["file"]),
            int(subject["line"]),
            subject.get("bound_name"),
        )
    if subject_type == "binding":
        return (
            normalize_relative_path(subject["file"]),
            int(subject["line"]),
            subject.get("name"),
        )
    if subject_type == "statement_range":
        return (
            normalize_relative_path(subject["file"]),
            int(subject["start_line"]),
            None,
        )
    return (
        normalize_relative_path(subject["file"]),
        int(subject["line"]),
        subject.get("name"),
    )


def parse_vulture(stdout: str, project_root: Path) -> list[ToolFinding]:
    findings = []
    for line in stdout.splitlines():
        stripped = line.strip()
        match = VULTURE_RE.match(stripped)
        if match:
            category = vulture_category(match.group("kind"), match.group("name"))
            if category is None:
                continue
            findings.append(
                ToolFinding(
                    tool="vulture",
                    category=category,
                    path=relative_path(match.group("path"), project_root),
                    line=int(match.group("line")),
                    name=match.group("name"),
                    raw=stripped,
                )
            )
            continue
        match = VULTURE_UNREACHABLE_RE.match(stripped)
        if match:
            findings.append(
                ToolFinding(
                    tool="vulture",
                    category="unreachable_statement",
                    path=relative_path(match.group("path"), project_root),
                    line=int(match.group("line")),
                    name=None,
                    raw=stripped,
                )
            )
    return findings


def parse_deadcode(stdout: str, project_root: Path) -> list[ToolFinding]:
    findings = []
    for raw_line in stdout.splitlines():
        stripped = ANSI_RE.sub("", raw_line.strip())
        match = DEADCODE_RE.match(stripped)
        if match:
            category = deadcode_category(match.group("kind"), match.group("name"))
            if category is None:
                continue
            findings.append(
                ToolFinding(
                    tool="deadcode",
                    category=category,
                    path=relative_path(match.group("path"), project_root),
                    line=int(match.group("line")),
                    name=match.group("name"),
                    raw=stripped,
                    rule_id=match.group("code"),
                )
            )
            continue
        match = DEADCODE_UNREACHABLE_RE.match(stripped)
        if match:
            findings.append(
                ToolFinding(
                    tool="deadcode",
                    category="unreachable_statement",
                    path=relative_path(match.group("path"), project_root),
                    line=int(match.group("line")),
                    name=None,
                    raw=stripped,
                    rule_id=match.group("code"),
                )
            )
    return findings


def collect_parse_warnings(tool: str, stdout: str) -> list[str]:
    if tool == "cull":
        if stdout.strip():
            try:
                json.loads(stdout)
            except json.JSONDecodeError as error:
                return [f"Cull JSON could not be parsed: {error}"]
        return []
    if tool == "vulture":
        return unparsed_vulture_lines(stdout)
    if tool == "deadcode":
        return unparsed_deadcode_lines(stdout)
    return [f"unknown tool parser: {tool}"]


def unparsed_vulture_lines(stdout: str) -> list[str]:
    warnings = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if VULTURE_RE.match(stripped) or VULTURE_UNREACHABLE_RE.match(stripped):
            continue
        warnings.append(stripped)
    return warnings


def unparsed_deadcode_lines(stdout: str) -> list[str]:
    warnings = []
    for raw_line in stdout.splitlines():
        stripped = ANSI_RE.sub("", raw_line.strip())
        if not stripped:
            continue
        if stripped.startswith("Well done!"):
            continue
        if DEADCODE_RE.match(stripped) or DEADCODE_UNREACHABLE_RE.match(stripped):
            continue
        warnings.append(stripped)
    return warnings


def vulture_category(kind: str, name: str) -> str | None:
    if kind == "import":
        return "unused_import"
    if kind == "variable":
        return "unused_local"
    if kind == "function":
        return "unused_function"
    if kind == "class":
        return "unused_class"
    if kind == "method":
        return "unused_private_method" if is_private_method_name(name) else "unused_function"
    return None


def deadcode_category(kind: str, name: str) -> str | None:
    if kind == "Import":
        return "unused_import"
    if kind in {"Variable", "Name"}:
        return "unused_local"
    if kind == "Function":
        return "unused_function"
    if kind == "Class":
        return "unused_class"
    if kind == "Method":
        return "unused_private_method" if is_private_method_name(name) else "unused_function"
    return None


def is_private_method_name(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def score_findings(
    expected: list[ExpectedFinding],
    findings: list[ToolFinding],
) -> dict[str, Any]:
    matched_expected: set[str] = set()
    true_positive: list[dict[str, Any]] = []
    false_positive: list[dict[str, Any]] = []

    for finding in sorted(findings, key=finding_sort_key):
        match = first_unmatched_expected(expected, matched_expected, finding)
        if match is None:
            false_positive.append(serialize_finding(finding))
            continue
        matched_expected.add(match.id)
        true_positive.append(
            {
                "expected_id": match.id,
                "finding": serialize_finding(finding),
            }
        )

    false_negative = [
        serialize_expected(finding)
        for finding in sorted(expected, key=lambda item: item.id)
        if finding.id not in matched_expected
    ]
    tp = len(true_positive)
    fp = len(false_positive)
    fn = len(false_negative)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": f1(tp, fp, fn),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def first_unmatched_expected(
    expected: list[ExpectedFinding],
    matched: set[str],
    finding: ToolFinding,
) -> ExpectedFinding | None:
    for item in expected:
        if item.id in matched:
            continue
        if not finding_matches(item, finding):
            continue
        return item
    return None


def finding_matches(expected: ExpectedFinding, finding: ToolFinding) -> bool:
    if expected.category != finding.category:
        return False
    if expected.path != finding.path:
        return False
    if not (expected.line <= finding.line <= expected.end_line):
        return False
    if expected.category == "unreachable_statement":
        return True
    return expected.name == finding.name


def aggregate(results: list[ProjectResult], tools: list[str]) -> dict[str, Any]:
    return {
        tool: finalize_metric(
            [
                result.tool_results[tool]["metrics"]
                for result in results
                if tool in result.tool_results
            ]
        )
        for tool in tools
    }


def aggregate_by_category(
    results: list[ProjectResult],
    tools: list[str],
) -> dict[str, dict[str, Any]]:
    categories: dict[str, dict[str, Any]] = {}
    for category in sorted(CATEGORIES):
        categories[category] = {}
        for tool in tools:
            category_metrics = []
            for result in results:
                expected = [
                    finding
                    for finding in result.expected
                    if finding.category == category
                ]
                finding_records = result.tool_results.get(tool, {}).get("metrics", {})
                if tool not in result.tool_results:
                    continue
                findings = [
                    deserialize_finding(record)
                    for record in finding_records.get("true_positive", [])
                    if record["finding"]["category"] == category
                ]
                findings.extend(
                    deserialize_finding(record)
                    for record in finding_records.get("false_positive", [])
                    if record["category"] == category
                )
                category_metrics.append(score_findings(expected, findings))
            categories[category][tool] = finalize_metric(category_metrics)
    return categories


def aggregate_cull_review(results: list[ProjectResult]) -> dict[str, Any]:
    return finalize_metric(
        [
            result.cull_high_plus_review["metrics"]
            for result in results
            if result.cull_high_plus_review is not None
        ]
    )


def timing_summary(results: list[ProjectResult], tools: list[str]) -> dict[str, Any]:
    summary = {}
    for tool in tools:
        medians = [
            result.tool_results[tool]["median_seconds"]
            for result in results
            if tool in result.tool_results
        ]
        rss_values = [
            result.tool_results[tool]["max_rss_bytes"]
            for result in results
            if tool in result.tool_results
            and result.tool_results[tool]["max_rss_bytes"] is not None
        ]
        summary[tool] = {
            "total_median_seconds": sum(medians),
            "max_project_median_seconds": max(medians, default=0.0),
            "max_rss_bytes": max(rss_values) if rss_values else None,
        }
    return summary


def finalize_metric(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(metric["tp"] for metric in metrics)
    fp = sum(metric["fp"] for metric in metrics)
    fn = sum(metric["fn"] for metric in metrics)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": f1(tp, fp, fn),
    }


def serialize_project_result(result: ProjectResult, tools: list[str]) -> dict[str, Any]:
    expected_by_category = {category: 0 for category in sorted(CATEGORIES)}
    for finding in result.expected:
        expected_by_category[finding.category] += 1
    payload = {
        "id": result.project.id,
        "shape": result.project.shape,
        "mode": result.project.mode,
        "source_roots": result.project.source_roots,
        "clean": result.project.clean,
        "large": result.project.large,
        "expected_findings": len(result.expected),
        "expected_by_category": expected_by_category,
        "tools": {
            tool: result.tool_results[tool]
            for tool in tools
            if tool in result.tool_results
        },
    }
    if result.cull_high_plus_review is not None:
        payload["cull_high_plus_review"] = result.cull_high_plus_review
    return payload


def serialize_run(run: CommandRun) -> dict[str, Any]:
    return {
        "exit_code": run.exit_code,
        "seconds": run.seconds,
        "max_rss_bytes": run.max_rss_bytes,
        "timed_out": run.timed_out,
    }


def serialize_expected(finding: ExpectedFinding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "category": finding.category,
        "path": finding.path,
        "name": finding.name,
        "line": finding.line,
        "end_line": finding.end_line,
        "rationale": finding.rationale,
    }


def serialize_finding(finding: ToolFinding) -> dict[str, Any]:
    return {
        "tool": finding.tool,
        "category": finding.category,
        "path": finding.path,
        "line": finding.line,
        "name": finding.name,
        "rule_id": finding.rule_id,
        "confidence": finding.confidence,
        "raw": finding.raw,
    }


def deserialize_finding(record: dict[str, Any]) -> ToolFinding:
    if "finding" in record:
        record = record["finding"]
    return ToolFinding(
        tool=record["tool"],
        category=record["category"],
        path=record["path"],
        line=int(record["line"]),
        name=record.get("name"),
        raw=record.get("raw", ""),
        rule_id=record.get("rule_id"),
        confidence=record.get("confidence"),
    )


def collect_tool_metadata(repo_root: Path, cull: Path, tools: list[str]) -> dict[str, Any]:
    metadata = {}
    for tool in tools:
        if tool == "cull":
            metadata[tool] = {
                "role": "subject under evaluation",
                "version": git_sha(repo_root) or "unknown",
                "command": os.fspath(cull),
            }
        elif tool == "vulture":
            metadata[tool] = {
                "role": "classic Python dead-code baseline",
                "version": command_version(["uvx", "vulture==2.16", "--version"]),
                "command": "uvx vulture==2.16 <source-roots>",
            }
        elif tool == "deadcode":
            metadata[tool] = {
                "role": "whole-codebase Python unused-code baseline",
                "version": command_version(
                    ["uvx", "--python", "3.11", "deadcode==2.4.1", "--version"]
                ),
                "command": "uvx --python 3.11 deadcode==2.4.1 <source-roots>",
            }
    return metadata


def command_version(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    text = (completed.stdout or completed.stderr).strip()
    return text.splitlines()[0] if text else "unknown"


def environment(repo_root: Path, runs: int, warmups: int, timeout: float) -> dict[str, Any]:
    return {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "cpu": cpu_name(),
        "memory_total_bytes": memory_total_bytes(),
        "python": sys.version.split()[0],
        "rust_profile": "release",
        "cull_commit": git_sha(repo_root),
        "runs": runs,
        "warmups": warmups,
        "timeout_seconds": timeout,
        "subprocess_startup_included": True,
    }


def cpu_name() -> str | None:
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return completed.stdout.strip() or None
        except OSError:
            return None
    return platform.processor() or None


def memory_total_bytes() -> int | None:
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return int(completed.stdout.strip())
        except (OSError, ValueError):
            return None
    return None


def git_sha(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    return completed.stdout.strip() or None


def write_raw_output(raw_root: Path, tool: str, project: str, run: CommandRun) -> Path:
    path = raw_root / tool / f"{project}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "$ " + " ".join(run.command),
                f"exit_code: {run.exit_code}",
                f"seconds: {run.seconds:.6f}",
                f"max_rss_bytes: {run.max_rss_bytes}",
                "",
                "[stdout]",
                run.stdout,
                "",
                "[stderr]",
                run.stderr,
            ]
        ),
        encoding="utf-8",
    )
    return path


def write_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Cull Benchmark Results",
        "",
        "## Aggregate",
        "",
        "| Tool | TP | FP | FN | Precision | Recall | F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tool, metrics in result["aggregate"].items():
        lines.append(metric_row(tool, metrics))
    if "cull_high_plus_review" in result:
        lines.append(metric_row("cull_high_plus_review", result["cull_high_plus_review"]))

    lines.extend(
        [
            "",
            "## Per Project",
            "",
            "| Project | Tool | Expected | TP | FP | FN | Precision | Recall | F1 | Median Seconds | Max RSS |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for project in result["projects"]:
        for tool, tool_result in project["tools"].items():
            metrics = tool_result["metrics"]
            lines.append(
                "| {project} | {tool} | {expected} | {tp} | {fp} | {fn} | "
                "{precision:.3f} | {recall:.3f} | {f1:.3f} | {seconds:.4f} | {rss} |".format(
                    project=project["id"],
                    tool=tool,
                    expected=project["expected_findings"],
                    tp=metrics["tp"],
                    fp=metrics["fp"],
                    fn=metrics["fn"],
                    precision=metrics["precision"],
                    recall=metrics["recall"],
                    f1=metrics["f1"],
                    seconds=tool_result["median_seconds"],
                    rss=tool_result["max_rss_bytes"],
                )
            )

    lines.extend(
        [
            "",
            "## Per Category",
            "",
            "| Category | Tool | TP | FP | FN | Precision | Recall | F1 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for category, tools in result["by_category"].items():
        for tool, metrics in tools.items():
            lines.append(metric_row(tool, metrics, prefix=category))

    lines.extend(
        [
            "",
            "## Timing",
            "",
            "| Tool | Total Median Seconds | Max Project Median Seconds | Max RSS |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for tool, timing in result.get("timing", {}).items():
        lines.append(
            "| {tool} | {total:.4f} | {project:.4f} | {rss} |".format(
                tool=tool,
                total=timing["total_median_seconds"],
                project=timing["max_project_median_seconds"],
                rss=timing["max_rss_bytes"],
            )
        )

    lines.extend(["", "## Environment", ""])
    for key, value in result["environment"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Tools", ""])
    for tool, metadata in result["tools"].items():
        lines.append(f"- `{tool}`: `{metadata['version']}` ({metadata['command']})")

    lines.extend(["", "## False Positives", ""])
    append_issue_section(lines, result, "false_positive")
    lines.extend(["", "## False Negatives", ""])
    append_issue_section(lines, result, "false_negative")
    lines.extend(["", "## Runner Warnings", ""])
    append_warning_section(lines, result)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def metric_row(label: str, metrics: dict[str, Any], *, prefix: str | None = None) -> str:
    first = f"{prefix} | {label}" if prefix else label
    return (
        f"| {first} | {metrics['tp']} | {metrics['fp']} | {metrics['fn']} | "
        f"{metrics['precision']:.3f} | {metrics['recall']:.3f} | {metrics['f1']:.3f} |"
    )


def append_issue_section(lines: list[str], result: dict[str, Any], key: str) -> None:
    any_issue = False
    for project in result["projects"]:
        for tool, tool_result in project["tools"].items():
            issues = tool_result["metrics"][key]
            if not issues:
                continue
            any_issue = True
            lines.append(f"### {project['id']} / {tool}")
            lines.append("")
            for issue in issues[:50]:
                lines.append(f"- `{json.dumps(issue, sort_keys=True)}`")
            if len(issues) > 50:
                lines.append(f"- ... {len(issues) - 50} more")
            lines.append("")
    if not any_issue:
        lines.append("None.")


def append_warning_section(lines: list[str], result: dict[str, Any]) -> None:
    any_warning = False
    for project in result["projects"]:
        for tool, tool_result in project["tools"].items():
            warnings = tool_result.get("parse_warnings", [])
            if not warnings:
                continue
            any_warning = True
            lines.append(f"### {project['id']} / {tool}")
            lines.append("")
            for warning in warnings[:50]:
                lines.append(f"- `{warning}`")
            if len(warnings) > 50:
                lines.append(f"- ... {len(warnings) - 50} more")
            lines.append("")
    if not any_warning:
        lines.append("None.")


def ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def f1(tp: int, fp: int, fn: int) -> float:
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def max_rss(runs: list[CommandRun]) -> int | None:
    values = [run.max_rss_bytes for run in runs if run.max_rss_bytes is not None]
    return max(values) if values else None


def finding_sort_key(finding: ToolFinding) -> tuple[str, str, int, str]:
    return (
        finding.category,
        finding.path,
        finding.line,
        finding.name or "",
    )


def relative_path(path: str, root: Path) -> str:
    candidate = Path(path)
    try:
        return normalize_relative_path(os.fspath(candidate.resolve().relative_to(root.resolve())))
    except ValueError:
        return normalize_relative_path(os.fspath(candidate))


def normalize_relative_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def count_loc(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in values:
        if value in seen:
            dupes.add(value)
        seen.add(value)
    return sorted(dupes)


def load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise SystemExit(f"file not found: {path}") from None
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid JSON in {path}: {error}") from None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def require_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"{context}: {key} must be a non-empty string")
    return value


def require_string_list(value: Any, key: str, context: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SystemExit(f"{context}: {key} must be a non-empty list")
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise SystemExit(f"{context}: {key}[{index}] must be a non-empty string")
        result.append(item)
    return result


def optional_string(value: Any, key: str, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SystemExit(f"{context}: {key} must be a string or null")
    return value


def optional_bool(value: Any, key: str, context: str) -> bool:
    if not isinstance(value, bool):
        raise SystemExit(f"{context}: {key} must be a boolean")
    return value


def require_int(data: dict[str, Any], key: str, context: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise SystemExit(f"{context}: {key} must be an integer")
    return value


def optional_int(value: Any, key: str, context: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise SystemExit(f"{context}: {key} must be an integer or null")
    return value


def normalize_paths(value: Any, repo_root: Path) -> Any:
    if isinstance(value, dict):
        return {key: normalize_paths(item, repo_root) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_paths(item, repo_root) for item in value]
    if isinstance(value, str):
        root = os.fspath(repo_root)
        return value.replace(root + os.sep, "")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
