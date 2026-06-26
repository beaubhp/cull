#![no_main]

use std::fs;

use culler_python::{DebugDefinitionsOptions, analyze_debug_definitions};
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let root = std::env::temp_dir().join(format!("culler-fuzz-project-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    if fs::create_dir_all(&root).is_err() {
        return;
    }
    if fs::write(root.join("module.py"), data).is_err() {
        return;
    }

    let _ = analyze_debug_definitions(DebugDefinitionsOptions {
        project_root: root,
        source_roots: Vec::new(),
        target_python: None,
    });
});
