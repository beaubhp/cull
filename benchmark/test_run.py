#!/usr/bin/env python3
"""Unit tests for the public benchmark runner."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


RUNNER_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("benchmark_run", RUNNER_PATH)
assert SPEC is not None
benchmark_run = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark_run
assert SPEC.loader is not None
SPEC.loader.exec_module(benchmark_run)


def finding(
    *,
    tool: str = "cull",
    category: str = "unused_function",
    path: str = "src/pkg/mod.py",
    line: int = 3,
    name: str | None = "legacy_path",
) -> object:
    return benchmark_run.ToolFinding(
        tool=tool,
        category=category,
        path=path,
        line=line,
        name=name,
        raw="raw",
    )


def expected(
    *,
    id: str = "case:unused_function:001",
    category: str = "unused_function",
    path: str = "src/pkg/mod.py",
    line: int = 3,
    end_line: int = 3,
    name: str | None = "legacy_path",
) -> object:
    return benchmark_run.ExpectedFinding(
        id=id,
        category=category,
        path=path,
        name=name,
        line=line,
        column=1,
        end_line=end_line,
        rationale="Known unused subject.",
    )


def command_run(
    *,
    tool: str = "cull",
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
) -> object:
    return benchmark_run.CommandRun(
        command=[tool],
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        seconds=0.01,
        max_rss_bytes=None,
        timed_out=timed_out,
    )


class BenchmarkRunnerTests(unittest.TestCase):
    def make_project(self, root: Path, project_id: str = "case") -> object:
        project_root = root / "projects" / project_id
        source = project_root / "src" / "pkg" / "mod.py"
        source.parent.mkdir(parents=True)
        source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
        expected_path = root / "expected" / f"{project_id}.json"
        expected_path.parent.mkdir(parents=True)
        expected_path.write_text(
            json.dumps(
                {
                    "project": project_id,
                    "root": f"projects/{project_id}",
                    "expected": [],
                }
            ),
            encoding="utf-8",
        )
        return benchmark_run.Project(
            id=project_id,
            path=project_root,
            expected_path=expected_path,
            mode="application",
            source_roots=["src"],
            shape="test project",
        )

    def test_suite_schema_validation_requires_object(self) -> None:
        with self.assertRaisesRegex(SystemExit, "JSON object"):
            benchmark_run.validate_suite_schema([])

    def test_suite_schema_validation_requires_project_list(self) -> None:
        with self.assertRaisesRegex(SystemExit, "projects must be a list"):
            benchmark_run.validate_suite_schema({"schema_version": 1, "projects": {}})

    def test_load_projects_rejects_malformed_source_roots(self) -> None:
        suite = {
            "schema_version": 1,
            "projects": [
                {
                    "id": "case",
                    "path": "projects/case",
                    "expected": "expected/case.json",
                    "mode": "application",
                    "source_roots": "src",
                    "shape": "test project",
                }
            ],
        }

        with self.assertRaisesRegex(SystemExit, "source_roots must be a non-empty list"):
            benchmark_run.load_projects(Path("benchmark"), suite)

    def test_expected_schema_validation_accepts_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "expected.json"
            path.write_text(
                json.dumps(
                    {
                        "project": "case",
                        "root": "projects/case",
                        "expected": [
                            {
                                "id": "case:unused_import:001",
                                "category": "unused_import",
                                "path": "src/pkg/mod.py",
                                "name": "json",
                                "line": 2,
                                "column": 1,
                                "end_line": 2,
                                "rationale": "Imported alias is not read.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            loaded = benchmark_run.load_expected(path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].category, "unused_import")

    def test_invalid_category_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "expected.json"
            path.write_text(
                json.dumps(
                    {
                        "expected": [
                            {
                                "id": "case:bad:001",
                                "category": "not_a_category",
                                "path": "src/pkg/mod.py",
                                "name": "x",
                                "line": 1,
                                "column": 1,
                                "end_line": 1,
                                "rationale": "bad",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "invalid category"):
                benchmark_run.load_expected(path)

    def test_duplicate_expected_ids_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)
            expected_findings = [
                expected(id="duplicate"),
                expected(id="duplicate", line=1, name="alpha"),
            ]

            with self.assertRaisesRegex(SystemExit, "duplicate expected ids"):
                benchmark_run.validate_corpus(
                    [project],
                    {"case": expected_findings},
                    enforce_size=False,
                )

    def test_missing_project_file_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)

            with self.assertRaisesRegex(SystemExit, "expected path missing"):
                benchmark_run.validate_corpus(
                    [project],
                    {"case": [expected(path="src/pkg/missing.py")]},
                    enforce_size=False,
                )

    def test_expected_metadata_must_match_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)
            project.expected_path.write_text(
                json.dumps(
                    {
                        "project": "other",
                        "root": "projects/case",
                        "expected": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "expected project metadata"):
                benchmark_run.validate_corpus(
                    [project],
                    {"case": []},
                    enforce_size=False,
                )

    def test_symbol_matching(self) -> None:
        self.assertTrue(benchmark_run.finding_matches(expected(), finding()))
        self.assertFalse(benchmark_run.finding_matches(expected(name="one"), finding(name="two")))

    def test_range_matching_for_unreachable_statement(self) -> None:
        item = expected(
            category="unreachable_statement",
            path="src/pkg/mod.py",
            line=10,
            end_line=14,
            name=None,
        )
        self.assertTrue(
            benchmark_run.finding_matches(
                item,
                finding(category="unreachable_statement", line=12, name=None),
            )
        )
        self.assertFalse(
            benchmark_run.finding_matches(
                item,
                finding(category="unreachable_statement", line=15, name=None),
            )
        )

    def test_score_counts_duplicate_tool_findings(self) -> None:
        metrics = benchmark_run.score_findings([expected()], [finding(), finding()])

        self.assertEqual(metrics["tp"], 1)
        self.assertEqual(metrics["fp"], 1)
        self.assertEqual(metrics["fn"], 0)

    def test_score_counts_unmatched_tool_finding_as_false_positive(self) -> None:
        metrics = benchmark_run.score_findings(
            [expected()],
            [finding(path="src/pkg/other.py")],
        )

        self.assertEqual(metrics["tp"], 0)
        self.assertEqual(metrics["fp"], 1)
        self.assertEqual(metrics["fn"], 1)

    def test_score_counts_unmatched_expected_finding_as_false_negative(self) -> None:
        metrics = benchmark_run.score_findings([expected()], [])

        self.assertEqual(metrics["tp"], 0)
        self.assertEqual(metrics["fp"], 0)
        self.assertEqual(metrics["fn"], 1)

    def test_precision_recall_f1_math(self) -> None:
        metrics = benchmark_run.score_findings(
            [expected(), expected(id="case:unused_function:002", line=8, name="beta")],
            [finding(), finding(path="src/pkg/other.py")],
        )

        self.assertEqual(metrics["tp"], 1)
        self.assertEqual(metrics["fp"], 1)
        self.assertEqual(metrics["fn"], 1)
        self.assertAlmostEqual(metrics["precision"], 0.5)
        self.assertAlmostEqual(metrics["recall"], 0.5)
        self.assertAlmostEqual(metrics["f1"], 0.5)

    def test_parse_cull_output(self) -> None:
        output = {
            "findings": [
                {
                    "finding_id": "CULL005-X",
                    "rule_id": "CULL005",
                    "confidence": "high",
                    "subject": {
                        "subject_type": "import_binding",
                        "file": "src/pkg/mod.py",
                        "line": 2,
                        "bound_name": "json",
                    },
                },
                {
                    "finding_id": "CULL006-Y",
                    "rule_id": "CULL006",
                    "confidence": "review",
                    "subject": {
                        "subject_type": "binding",
                        "file": "src/pkg/mod.py",
                        "line": 5,
                        "name": "value",
                    },
                },
            ]
        }

        high = benchmark_run.parse_cull(json.dumps(output), include_review=False)
        reported = benchmark_run.parse_cull(json.dumps(output), include_review=True)

        self.assertEqual([item.category for item in high], ["unused_import"])
        self.assertEqual([item.category for item in reported], ["unused_import", "unused_local"])

    def test_parse_vulture_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "src" / "pkg" / "mod.py"
            path.parent.mkdir(parents=True)
            path.write_text("", encoding="utf-8")
            parsed = benchmark_run.parse_vulture(
                f"{path}:4: unused function 'legacy_path' (60% confidence)\n"
                f"{path}:9: unreachable code\n",
                root,
            )

        self.assertEqual([item.category for item in parsed], ["unused_function", "unreachable_statement"])
        self.assertEqual(parsed[0].path, "src/pkg/mod.py")

    def test_parse_deadcode_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "src" / "pkg" / "mod.py"
            path.parent.mkdir(parents=True)
            path.write_text("", encoding="utf-8")
            parsed = benchmark_run.parse_deadcode(
                f"\x1b[31m{path}:4:1: DC02 Function `legacy_path` is never used\x1b[0m\n"
                f"{path}:9:1: DC10 unreachable code\n",
                root,
            )

        self.assertEqual([item.category for item in parsed], ["unused_function", "unreachable_statement"])
        self.assertEqual(parsed[0].rule_id, "DC02")

    def test_validate_command_run_allows_known_finding_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)

            benchmark_run.validate_command_run(
                "cull",
                project,
                command_run(tool="cull", exit_code=1, stdout='{"findings": []}'),
            )
            benchmark_run.validate_command_run(
                "vulture",
                project,
                command_run(tool="vulture", exit_code=3, stdout="unused.py:1: unused function 'x'\n"),
            )
            benchmark_run.validate_command_run(
                "deadcode",
                project,
                command_run(tool="deadcode", exit_code=0),
            )

    def test_validate_command_run_rejects_failed_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)

            with self.assertRaisesRegex(SystemExit, "vulture failed"):
                benchmark_run.validate_command_run(
                    "vulture",
                    project,
                    command_run(tool="vulture", exit_code=2, stderr="traceback"),
                )

            with self.assertRaisesRegex(SystemExit, "deadcode wrote stderr"):
                benchmark_run.validate_command_run(
                    "deadcode",
                    project,
                    command_run(tool="deadcode", stderr="unexpected warning"),
                )

            with self.assertRaisesRegex(SystemExit, "cull timed out"):
                benchmark_run.validate_command_run(
                    "cull",
                    project,
                    command_run(tool="cull", exit_code=124, timed_out=True),
                )

    def test_validate_parse_warnings_rejects_unparsed_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)

            with self.assertRaisesRegex(SystemExit, "could not be fully parsed"):
                benchmark_run.validate_parse_warnings(
                    "cull",
                    project,
                    ["Cull JSON could not be parsed"],
                )

    def test_markdown_and_json_report_generation_smoke(self) -> None:
        result = {
            "aggregate": {
                "cull": {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
            },
            "by_category": {
                "unused_function": {
                    "cull": {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
                }
            },
            "projects": [
                {
                    "id": "case",
                    "expected_findings": 1,
                    "tools": {
                        "cull": {
                            "median_seconds": 0.01,
                            "max_rss_bytes": 123,
                            "metrics": {
                                "tp": 1,
                                "fp": 0,
                                "fn": 0,
                                "precision": 1.0,
                                "recall": 1.0,
                                "f1": 1.0,
                                "false_positive": [],
                                "false_negative": [],
                            },
                        }
                    },
                }
            ],
            "environment": {"python": "3.x"},
            "tools": {"cull": {"version": "test", "command": "cull"}},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "latest.json"
            md_path = root / "latest.md"
            benchmark_run.write_json(json_path, result)
            benchmark_run.write_markdown(md_path, result)

            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(loaded["aggregate"]["cull"]["tp"], 1)
        self.assertIn("Cull Benchmark Results", markdown)
        self.assertIn("False Positives", markdown)


if __name__ == "__main__":
    unittest.main()
