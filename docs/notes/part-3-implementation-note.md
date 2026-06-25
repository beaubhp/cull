# Part 3 Implementation Note

Part 3 implements conservative root-based reachability and the second finding family:
`CULL003` and `CULL004`.

## Scope Implemented

- `root_coverage = "complete" | "partial"` configuration.
- Derived `RootCoverage::Complete`, `Partial`, `Absent`, and `NotApplicable` states.
- Configured module and object roots, including exact `module:object.attr` nested resolution.
- `[project.scripts]` and `[project.gui-scripts]` root discovery.
- Module-import execution for configured object roots, script roots, and external-surface roots.
- Dynamic script metadata and unresolved valid script targets as partial root information unless
  complete coverage is asserted.
- Malformed script metadata and malformed object references as exit-code `2` input errors.
- Main-guard roots for narrow `__name__ == "__main__"` and inverse forms.
- Local `__main__.py` package/module roots.
- Isolated `Production`, `Test`, and `ExternalSurface` reachability domains.
- Library and auto external-surface reachability that protects public/exported APIs and their
  private helpers without leaking into production reachability.
- Runtime scanning that distinguishes module execution, function bodies, class bodies, direct calls,
  callable escapes, class construction, and method contexts.
- Direct class construction activation for statically resolved metaclass `__call__`, `__new__`, and
  `__init__`, not every method.
- Localized uncertainty for unresolved custom metaclass construction.
- Exact method activation for configured nested roots and simple instance method calls with local
  instance provenance.
- Conservative callable escape activation for arguments, returns, containers, attributes, and
  subscripts.
- Lazy annotation and type-only reference phases do not establish production runtime reachability.
- Static runtime-edge projection for weak dead-cluster classification.
- `CULL003` and `CULL004` findings with root coverage, root summaries, domain reachability flags,
  and deterministic evidence.

## Test Coverage

Focused Part 3 tests cover:

- configured complete roots and direct call activation
- weakly connected dead clusters overriding simple unreferenced-first priority
- main-guard roots without blanket module liveness
- valid unresolved script targets producing `Partial`
- dynamic script metadata with a static table still using the static table
- configured object roots importing their defining module before target activation
- absent root coverage disabling root-unreachable findings
- auto-mode root-unreachable confidence under partial and complete root coverage
- auto-mode external-surface protection for exported private helpers
- lazy annotation references preventing unreferenced findings without becoming runtime reachability
- CLI JSON exit-code `2` behavior for complete-root validation failures
- complete coverage failing closed for unresolved script targets
- malformed script references as configuration errors
- test reachability remaining isolated from production reachability
- library external-surface reachability protecting private helpers
- library private dead clusters producing high-confidence root-unreachable findings
- direct class construction activating `__init__` but not every method
- direct class construction activating statically resolved metaclass `__call__`
- unresolved custom metaclass construction downgrading localized method-side findings to `Review`
- configured nested method roots resolving exactly
- unresolved configured module roots preserving their root kind in output
- callable argument escapes conservatively activating callback bodies

## Verification

Commands run during implementation:

```bash
cargo check
cargo test -p cull-python --test part2
cargo test -p cull-python --test part3
cargo test
cargo fmt --all -- --check
cargo clippy --all-targets -- -D warnings
git diff --check
```
