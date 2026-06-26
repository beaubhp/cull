use std::{fs, path::Path};

use culler_core::{
    BindingKind, CandidateStatus, FindingConfidence, FindingRule, FindingSubject, FindingType,
    ProjectMode,
};
use culler_python::{analyze_check, CheckOptions};

fn write_file(root: &Path, path: &str, contents: &str) {
    let path = root.join(path);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, contents).unwrap();
}

fn check_project(root: &Path) -> culler_core::CheckOutput {
    analyze_check(CheckOptions {
        project_root: root.to_path_buf(),
        source_roots: vec![root.join("src")],
        target_python: None,
        mode: Some(ProjectMode::Application),
        allow_partial: false,
    })
    .unwrap()
}

fn check_project_in_mode(root: &Path, mode: ProjectMode) -> culler_core::CheckOutput {
    analyze_check(CheckOptions {
        project_root: root.to_path_buf(),
        source_roots: vec![root.join("src")],
        target_python: None,
        mode: Some(mode),
        allow_partial: false,
    })
    .unwrap()
}

fn rule_findings(
    output: &culler_core::CheckOutput,
    rule: FindingRule,
) -> Vec<&culler_core::Finding> {
    output
        .findings
        .iter()
        .filter(|finding| finding.rule_id == rule)
        .collect()
}

fn has_rule_name(output: &culler_core::CheckOutput, rule: FindingRule, name: &str) -> bool {
    output
        .findings
        .iter()
        .any(|finding| finding.rule_id == rule && finding.subject.name() == name)
}

#[test]
fn library_public_unexported_definitions_are_review_not_silent() {
    let temp = tempfile::tempdir().unwrap();
    write_file(
        temp.path(),
        "pyproject.toml",
        "[tool.culler]\nsrc = 'src'\nmode = 'library'\nroot_coverage = 'complete'\nroots = ['pkg.app:main']\n",
    );
    write_file(
        temp.path(),
        "src/pkg/__init__.py",
        "from .api import exported\n__all__ = ['exported']\n",
    );
    write_file(
        temp.path(),
        "src/pkg/api.py",
        "def exported():\n    return 1\n",
    );
    write_file(temp.path(), "src/pkg/app.py", "def main():\n    return 1\n");
    write_file(
        temp.path(),
        "src/pkg/internal.py",
        "def public_helper():\n    return 2\n\nclass PublicWidget:\n    pass\n",
    );

    let output = check_project_in_mode(temp.path(), ProjectMode::Library);
    let public_helper = output
        .findings
        .iter()
        .find(|finding| {
            finding.rule_id == FindingRule::Cull001 && finding.subject.name() == "public_helper"
        })
        .unwrap_or_else(|| panic!("missing public_helper review finding; output: {output:#?}"));
    assert_eq!(public_helper.confidence, FindingConfidence::Review);

    let public_widget = output
        .findings
        .iter()
        .find(|finding| {
            finding.rule_id == FindingRule::Cull002 && finding.subject.name() == "PublicWidget"
        })
        .unwrap_or_else(|| panic!("missing PublicWidget review finding; output: {output:#?}"));
    assert_eq!(public_widget.confidence, FindingConfidence::Review);
    assert!(
        !has_rule_name(&output, FindingRule::Cull001, "exported"),
        "{output:#?}"
    );
}

#[test]
fn unused_import_bindings_are_exact_and_export_aware() {
    let temp = tempfile::tempdir().unwrap();
    write_file(temp.path(), "src/pkg/__init__.py", "");
    write_file(
        temp.path(),
        "src/pkg/api.py",
        "class Used:\n    pass\n\nclass TypeOnly:\n    pass\n\nclass Exported:\n    pass\n\nclass Late:\n    pass\n\nclass Unused:\n    pass\n",
    );
    write_file(
        temp.path(),
        "src/pkg/mod.py",
        concat!(
            "from __future__ import annotations\n",
            "from typing import TYPE_CHECKING\n",
            "import json\n",
            "import math as mathematics\n",
            "import os, sys\n",
            "from pkg.api import Used, Unused as Alias, Exported\n",
            "__all__ = ['Exported']\n",
            "print(mathematics.pi)\n",
            "def consume(value: Used) -> None:\n",
            "    instance = Used()\n",
            "    return instance\n",
            "def late_import_read_before_write() -> None:\n",
            "    print(Late)\n",
            "    from pkg.api import Late\n",
            "    pass\n",
            "if TYPE_CHECKING:\n",
            "    from pkg.api import TypeOnly\n",
            "    def typed(value: TypeOnly) -> None:\n",
            "        pass\n",
        ),
    );

    let output = check_project(temp.path());
    let unused_imports = rule_findings(&output, FindingRule::Cull005);
    let names = unused_imports
        .iter()
        .map(|finding| finding.subject.name())
        .collect::<Vec<_>>();

    assert!(names.contains(&"json"), "{output:#?}");
    assert!(names.contains(&"os"), "{output:#?}");
    assert!(names.contains(&"sys"), "{output:#?}");
    assert!(names.contains(&"Alias"), "{output:#?}");
    assert!(names.contains(&"Late"), "{output:#?}");
    assert!(!names.contains(&"mathematics"), "{output:#?}");
    assert!(!names.contains(&"Used"), "{output:#?}");
    assert!(!names.contains(&"TypeOnly"), "{output:#?}");
    assert!(!names.contains(&"Exported"), "{output:#?}");
    for name in ["json", "os", "sys", "Alias"] {
        let finding = unused_imports
            .iter()
            .find(|finding| finding.subject.name() == name)
            .unwrap_or_else(|| panic!("missing unused import {name}; output: {output:#?}"));
        assert!(matches!(
            finding.subject,
            FindingSubject::ImportBinding { .. }
        ));
        assert_eq!(finding.finding_type, FindingType::UnusedImport);
        assert_eq!(
            finding.confidence,
            FindingConfidence::High,
            "{name}: {finding:#?}"
        );
    }
    let late_import = unused_imports
        .iter()
        .find(|finding| finding.subject.name() == "Late")
        .unwrap_or_else(|| panic!("missing unused import Late; output: {output:#?}"));
    assert_eq!(late_import.confidence, FindingConfidence::Review);
}

#[test]
fn unused_local_bindings_are_binding_exact() {
    let temp = tempfile::tempdir().unwrap();
    write_file(temp.path(), "src/pkg/__init__.py", "");
    write_file(
        temp.path(),
        "src/pkg/mod.py",
        concat!(
            "def build():\n",
            "    return 1\n\n",
            "def target(value):\n",
            "    unused = build()\n",
            "    used = build()\n",
            "    print(used)\n",
            "    print(read_before_write)\n",
            "    read_before_write = build()\n",
            "    overwritten = build()\n",
            "    overwritten = 2\n",
            "    print(overwritten)\n",
            "    left, right = (1, 2)\n",
            "    print(left)\n",
            "    annotated: int = 1\n",
            "    declared_only: int\n",
            "    for item in []:\n",
            "        pass\n",
            "    with open(__file__) as handle:\n",
            "        pass\n",
            "    if (named := value):\n",
            "        pass\n",
            "    match value:\n",
            "        case {'kind': captured}:\n",
            "            pass\n",
            "    _ = build()\n",
            "    _private = build()\n",
        ),
    );

    let output = check_project(temp.path());
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "unused"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "read_before_write"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "overwritten"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "right"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "annotated"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "item"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "handle"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "named"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "captured"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull006, "_private"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull006, "used"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull006, "left"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull006, "declared_only"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull006, "_"),
        "{output:#?}"
    );

    let private = output
        .findings
        .iter()
        .find(|finding| {
            finding.rule_id == FindingRule::Cull006 && finding.subject.name() == "_private"
        })
        .unwrap();
    assert_eq!(private.confidence, FindingConfidence::Review);
    assert!(rule_findings(&output, FindingRule::Cull006)
        .iter()
        .all(|finding| {
            matches!(
                finding.subject,
                FindingSubject::Binding {
                    binding: culler_core::FindingBinding {
                        binding_kind: BindingKind::Assignment
                            | BindingKind::AnnotatedAssignment
                            | BindingKind::ForTarget
                            | BindingKind::WithTarget
                            | BindingKind::MatchCapture
                            | BindingKind::NamedExpression,
                        ..
                    }
                }
            ) && finding.status == CandidateStatus::Reported
        }));
}

#[test]
fn unreachable_statement_range_is_primary_for_contained_subjects() {
    let temp = tempfile::tempdir().unwrap();
    write_file(temp.path(), "src/pkg/__init__.py", "");
    write_file(
        temp.path(),
        "src/pkg/mod.py",
        concat!(
            "from typing import TYPE_CHECKING\n\n",
            "def target():\n",
            "    return\n",
            "    import os\n",
            "    unused = 1\n",
            "    def hidden():\n",
            "        pass\n\n",
            "def constants():\n",
            "    if False:\n",
            "        not_reported = 1\n",
            "    if TYPE_CHECKING:\n",
            "        type_only = 1\n",
        ),
    );

    let output = check_project(temp.path());
    let unreachable = rule_findings(&output, FindingRule::Cull007);
    assert_eq!(unreachable.len(), 1, "{output:#?}");
    assert_eq!(unreachable[0].confidence, FindingConfidence::High);
    assert!(matches!(
        unreachable[0].subject,
        FindingSubject::StatementRange { .. }
    ));
    assert!(
        !has_rule_name(&output, FindingRule::Cull005, "os"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull006, "unused"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull001, "hidden"),
        "{output:#?}"
    );
}

#[test]
fn unreachable_statement_ranges_cover_raise_break_and_continue() {
    let temp = tempfile::tempdir().unwrap();
    write_file(temp.path(), "src/pkg/__init__.py", "");
    write_file(
        temp.path(),
        "src/pkg/mod.py",
        concat!(
            "def after_raise():\n",
            "    raise RuntimeError()\n",
            "    dead_after_raise = 1\n\n",
            "def after_break():\n",
            "    while True:\n",
            "        break\n",
            "        dead_after_break = 1\n\n",
            "def after_continue():\n",
            "    while True:\n",
            "        continue\n",
            "        dead_after_continue = 1\n",
        ),
    );

    let output = check_project(temp.path());
    let unreachable = rule_findings(&output, FindingRule::Cull007);
    assert_eq!(unreachable.len(), 3, "{output:#?}");
    assert!(unreachable.iter().all(|finding| {
        finding.confidence == FindingConfidence::High
            && matches!(finding.subject, FindingSubject::StatementRange { .. })
    }));
}

#[test]
fn unused_private_methods_are_narrow_and_owner_aware() {
    let temp = tempfile::tempdir().unwrap();
    write_file(temp.path(), "src/pkg/__init__.py", "");
    write_file(
        temp.path(),
        "src/pkg/mod.py",
        concat!(
            "class Service:\n",
            "    def public(self):\n",
            "        self._used()\n",
            "        callback = self._read\n",
            "        values = [item for item in self._items() if self._allowed(item)]\n",
            "        label = f'{self._label():>{self._width()}}'\n",
            "        return callback, values, label\n\n",
            "    def _used(self):\n",
            "        pass\n\n",
            "    def _read(self):\n",
            "        pass\n\n",
            "    def _items(self):\n",
            "        return []\n\n",
            "    def _allowed(self, item):\n",
            "        return True\n\n",
            "    def _label(self):\n",
            "        return 'service'\n\n",
            "    def _width(self):\n",
            "        return 8\n\n",
            "    def _unused(self):\n",
            "        pass\n\n",
            "    def __private_unused(self):\n",
            "        pass\n\n",
            "    def __str__(self):\n",
            "        return 'service'\n\n",
            "    @property\n",
            "    def _property(self):\n",
            "        return 1\n\n",
            "class Dead:\n",
            "    def _method(self):\n",
            "        pass\n\n",
            "def main():\n",
            "    service = Service()\n",
            "    service.public()\n",
        ),
    );
    write_file(
        temp.path(),
        "pyproject.toml",
        "[tool.culler]\nsrc = 'src'\nmode = 'application'\nroot_coverage = 'complete'\nroots = ['pkg.mod:main']\n",
    );

    let output = check_project(temp.path());
    assert!(
        has_rule_name(&output, FindingRule::Cull008, "_unused"),
        "{output:#?}"
    );
    assert!(
        has_rule_name(&output, FindingRule::Cull008, "__private_unused"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull008, "_used"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull008, "_read"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull008, "_items"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull008, "_allowed"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull008, "_label"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull008, "_width"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull008, "__str__"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull008, "_property"),
        "{output:#?}"
    );
    assert!(
        !has_rule_name(&output, FindingRule::Cull008, "_method"),
        "{output:#?}"
    );
    assert!(rule_findings(&output, FindingRule::Cull008)
        .iter()
        .all(|finding| {
            matches!(finding.subject, FindingSubject::Definition { .. })
                && finding.finding_type == FindingType::UnusedPrivateMethod
                && finding.confidence == FindingConfidence::High
        }));
}
