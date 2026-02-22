---
name: dependency-audit
description: Audit codebase syntax and API usage against up-to-date documentation for all project dependencies. Use when the user wants to check if their code follows current library conventions, detect deprecated APIs, or ensure compatibility with installed package versions.
tools: Read, Glob, Grep, Bash, WebFetch, WebSearch, Task
---

# Dependency Audit Skill

Audit the codebase to ensure all code follows the current documentation standards for each dependency, flagging deprecated APIs, outdated patterns, and version-specific breaking changes.

## Workflow

### Phase 1: Gather Dependencies

Read the project's dependency manifest(s) to extract package names and version constraints.

**Priority order — read whichever exist:**

```bash
# Python
cat pyproject.toml
cat requirements.txt
cat requirements*.txt

# Node
cat package.json

# Rust
cat Cargo.toml

# Go
cat go.mod
```

Extract each dependency name and its pinned or constrained version. For `pyproject.toml`, parse both `[project.dependencies]` and `[dependency-groups]` (or `[tool.uv.dev-dependencies]`). Record the **exact installed version** where possible:

```bash
# Python — get installed versions
uv pip list --format=json 2>/dev/null || pip list --format=json 2>/dev/null

# Node
cat package-lock.json | python3 -c "import json,sys; d=json.load(sys.stdin); [print(k,v['version']) for k,v in d.get('packages',{}).items() if k and not k.startswith('node_modules/node_modules')]" 2>/dev/null
```

Build a list of `(package, resolved_version)` pairs. Skip packages with no public documentation (private packages, local paths).

---

### Phase 2: Parallel Documentation Fetch

For each package in the list, spawn a **dedicated research agent** in parallel. Each agent is responsible for one package only.

**Agent prompt template:**

```
You are auditing the dependency: {package_name} version {version}.

1. Find the official documentation or changelog for this exact version.
   Search: "{package_name} {version} documentation API reference"
   Also check: "{package_name} {version} changelog breaking changes migration"

2. Identify the following for this version:
   - Deprecated functions, classes, or patterns (with their replacements)
   - Removed APIs compared to prior major versions
   - New recommended idioms or patterns introduced in this version
   - Import path changes

3. Return a structured summary:
   PACKAGE: {package_name}
   VERSION: {version}
   DEPRECATED_APIS: [list of deprecated items with replacements]
   REMOVED_APIS: [list of removed items]
   NEW_PATTERNS: [new recommended patterns]
   IMPORT_CHANGES: [any import path changes]
   DOCS_URL: [URL used]
```

Launch all agents in a single parallel batch. Collect all results before proceeding.

**Common documentation sources to check:**
| Ecosystem | Source |
|-----------|--------|
| Python    | `https://pypi.org/project/{pkg}/` then official docs link |
| Node/npm  | `https://www.npmjs.com/package/{pkg}` then official docs |
| Rust      | `https://docs.rs/{pkg}/{version}` |
| Go        | `https://pkg.go.dev/{module}@{version}` |

---

### Phase 3: Codebase Audit

With the documentation summaries from Phase 2, scan the codebase for usages of each package.

For each package:

1. **Find all imports and usages:**
   ```bash
   # Python imports
   grep -rn "^import {pkg}\|^from {pkg}" src/ --include="*.py"

   # Node imports
   grep -rn "require('{pkg}')\|from '{pkg}'" src/ --include="*.{js,ts,jsx,tsx}"
   ```

2. **Check for deprecated/removed APIs:**
   - Use the deprecated and removed API lists from Phase 2
   - Search each deprecated symbol across the codebase
   - Record file path, line number, current usage, and recommended replacement

3. **Check import paths:**
   - Verify imports match the current recommended import paths
   - Flag old import paths that have moved in the current version

4. **Check usage patterns:**
   - Compare call signatures against current docs (e.g., renamed parameters, dropped keyword args)
   - Flag patterns the docs now discourage

---

### Phase 4: Report

Output a structured audit report grouped by package. Only include packages where issues were found.

```markdown
# Dependency Audit Report

**Audited:** {date}
**Dependencies scanned:** {N}
**Issues found:** {total_issues}

---

## {package_name} {version}

**Docs:** {docs_url}

### ⚠️ Deprecated APIs in use

| File | Line | Current Usage | Recommended Replacement |
|------|------|---------------|------------------------|
| `src/foo.py` | 42 | `pkg.old_func()` | `pkg.new_func()` |

### ❌ Removed APIs in use

| File | Line | Usage | Notes |
|------|------|-------|-------|

### 📦 Import path changes

| File | Line | Current Import | Correct Import |
|------|------|----------------|----------------|

### 💡 Pattern improvements

Describe any modern patterns the codebase should migrate to, with before/after examples.

---

## ✅ No issues found

The following packages had no audit findings: {list}

---

## Summary

- {N} deprecated API usages to update
- {N} removed APIs that will break at runtime
- {N} import paths to fix
- {N} pattern improvements recommended

**Suggested next steps:**
1. Fix removed APIs first (runtime breakage)
2. Update deprecated APIs before next major upgrade
3. Adopt new patterns opportunistically during refactors
```

## Guidelines

- **Be version-specific.** A deprecation in v2.0 is not relevant if the project uses v1.x.
- **Skip false positives.** Only flag something if you found explicit documentation stating it is deprecated/removed for the installed version.
- **Do not modify files.** This skill is read-only. It audits and reports — the user decides what to fix.
- **Prioritize severity:** removed APIs (breaks at runtime) > deprecated APIs (future breakage) > pattern improvements (nice-to-have).
- **If docs are unavailable** for a package (private, obscure, or no internet access), note it in the report and skip that package rather than guessing.
