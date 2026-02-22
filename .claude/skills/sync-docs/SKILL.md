---
name: sync-docs
description: Audits and corrects documentation to match the current state of the codebase. Use when the user asks to "sync docs", "update documentation", "fix outdated docs", "update README", "clean up docs", or "make docs accurate".
disable-model-invocation: true
---

# Documentation Sync

You are auditing and correcting documentation so it accurately reflects the current state of the codebase.

## Step 1 — Gather Live Context

Before reading anything, collect the current state of the repo:

- Working directory: !`pwd`
- Project files (top-level): !`ls -1`
- Git log (last 10 commits): !`git log --oneline -10 2>/dev/null || echo "not a git repo"`

## Step 2 — Understand the Project

Read key config and entry-point files to understand the project's tech stack, build commands, structure, and dependencies. Adapt to what you find — not every project has every file.

Check these in order and read the ones that exist:

**Package / dependency manifests** (read the first one found):
- `package.json`
- `pyproject.toml`
- `Cargo.toml`
- `go.mod`
- `composer.json`
- `Gemfile`
- `uv.lock` or `requirements.txt` (for environment variable and dependency info)

**Project config files** (read any that exist):
- `astro.config.*`, `next.config.*`, `vite.config.*`, `webpack.config.*`
- `Dockerfile`, `docker-compose*.yml` / `docker-compose*.yaml`
- `.env.example`
- `Makefile`
- `CLAUDE.md`

**Directory structure** (skim the top-level shape):
- Run: !`find . -maxdepth 3 -not -path './.git/*' -not -path './node_modules/*' -not -path './.venv/*' -not -path './dist/*' -not -path './__pycache__/*' -type f -name '*.json' -o -type f -name '*.toml' -o -type f -name '*.yaml' -o -type f -name '*.yml' | sort | head -60`

Use this knowledge as your ground truth for what is accurate.

## Step 3 — Find All Documentation Files

Locate every documentation file in the repo:

- `README.md` (root)
- `CLAUDE.md` (root)
- `.env.example` (root)
- `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md` (root, if present)
- Everything inside `docs/` (all depths)
- Everything inside `wiki/` (all depths)
- Any `*.md` files at the root level

Skip files inside `node_modules/`, `.venv/`, `dist/`, `build/`, `.git/`.

## Step 4 — Audit Each Documentation File

Read each file found in Step 3 and check for these categories of discrepancy:

**Commands and scripts**
- Build, test, dev, lint, deploy commands that no longer match `package.json` scripts or `Makefile` targets
- Install instructions that reference the wrong package manager or missing flags

**File and directory paths**
- References to files or directories that no longer exist
- Missing references to new significant files or directories

**Configuration and environment variables**
- Variables in `.env.example` not used anywhere in the codebase
- Variables used in the code but missing from `.env.example`
- Port numbers, service names, or connection strings that changed

**Dependencies and tools**
- Package names or versions that are outdated or removed
- Tool references (Node version, Python version, Docker version) that contradict the config files

**Behaviour descriptions**
- Feature descriptions that no longer match the actual implementation
- Incorrect routing, API endpoints, or data flow descriptions

**Only flag something as wrong if you can verify it against the actual code.** Do not change things based on assumptions.

## Step 5 — Fix Each Discrepancy

For each verified discrepancy, edit the documentation file directly. Follow these rules:

- **Only change what is verifiably wrong** — do not rewrite prose, improve style, or add sections the author didn't intend.
- **Preserve the author's voice and structure** — minimum diff, maximum accuracy.
- **Do not create new documentation files.**
- **Do not delete documentation files.**
- **Do not add new sections** unless a significant feature is completely undocumented and the omission would cause user confusion.

## Step 6 — Report

After all edits, output a concise summary:

```
## Documentation Sync Report

### Files changed
- `README.md` — updated install command from `npm install` to `pnpm install`
- `docs/config.md` — removed reference to deleted `config.yaml`, added `DATABASE_URL` env var

### Files unchanged
- `CLAUDE.md` — accurate
- `.env.example` — accurate

### Items skipped (require human judgment)
- `README.md` line 42: describes feature X but implementation is ambiguous — left unchanged
```

If no discrepancies were found: state that all documentation is accurate and no changes were made.
