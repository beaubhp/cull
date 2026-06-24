# Part 1D Implementation Note

Part 1D completes Part 1 by adding site-aware annotation facts, type-only domains, overload
grouping, definition-effect evidence, removal-risk summaries, and internal same-module candidates.
It remains debug/internal only: no cross-module import resolution, export model, roots, or public
findings are introduced.

Implemented semantics:

- demand-created annotation scopes and contexts
- site-aware annotation evaluations: eager, stringified, deferred, and never-evaluated
- function parameter and return annotations, annotated assignments, type aliases, type-parameter
  bounds, and type-parameter defaults
- type-parameter bindings inside their annotation scopes, including generic class bodies and method
  annotations that depend on class type parameters
- explicit quoted forward-reference parsing with type-only references and `Literal[...]` payloads
  left uninterpreted
- Python 3.14 ordinary annotations as lazy annotation references by default
- `from __future__ import annotations` and explicit strings as type-only annotation references
- function-local variable annotations as never runtime-evaluated type-only references
- symbol-proven `TYPE_CHECKING` branch tagging for `typing` and `typing_extensions`, including
  aliasing and shadowing
- deterministic production/test origin tagging with Cull config, pytest metadata, conventional test
  directories, filename patterns, and default-production evidence
- symbol-proven `Literal` payload suppression and `typing.overload` /
  `typing_extensions.overload` declaration detection
- overload grouping with declarations suppressed as non-reportable and implementation grouped when
  present; missing implementations emit internal diagnostic `CULL_P1107`
- metaclass references and `MetaclassEvaluation` definition effects
- structural definition-effect facts and categorical removal-risk summaries
- internal same-module candidate facts and snapshots without adding a stable public CLI schema
- CPython `symtable` oracle coverage for annotation and type-parameter scope facts

Deliberately conservative:

- type-only and lazy annotation references can prevent internal unreferenced candidates, but they do
  not establish ordinary runtime reachability
- string annotation parsing never evaluates annotation code
- unsupported string annotations produce structured diagnostics instead of execution
- unsupported string annotations suppress internal candidates in the affected module
- unsupported same-module flow, residual runtime lookup, flow uncertainty, and class-body fallback
  lookup suppress internal candidates for the possible same-module bindings
- candidate facts are internal and include cross-module analysis deferred evidence
- methods and nested functions remain non-reportable
- definitions under `if TYPE_CHECKING:` are non-reportable

Part 1D fixtures cover site-aware annotation phases, string forward references, `Literal` string
payload suppression, `TYPE_CHECKING`, configured test-origin evidence, overload grouping,
definition effects, removal risk, internal candidates, metaclass effects, CPython annotation-scope
oracle facts, target-version annotation behavior, and deterministic JSON snapshots.

Verification:

```bash
cargo fmt --all -- --check
cargo test
cargo clippy --all-targets -- -D warnings
cargo check --manifest-path fuzz/Cargo.toml
git diff --check
```
