# Production Core 0.1

## Ownership and Distribution

The canonical source is video2book's skill-local `src/bookcore/`. Other tools
bundle byte-identical copies in their own `_bookcore/` namespaces. Runtime
execution never imports a sibling checkout. `RELEASE.json` pins the version
and SHA-256 of each file. The original MIT license is included.
Do not edit generated copies. From the video2book checkout:

```bash
python skills/video2book/scripts/sync_bookcore.py --workspace /path/to/container --write
python skills/video2book/scripts/sync_bookcore.py --workspace /path/to/container
python -m pytest skills/video2book/tests/test_bookcore.py
```

The second command is read-only. The contract suite tests all available bundles;
a standalone checkout tests its own bundle. Also run all domain regression tests.

## Stable Contracts

- `SourceRange`: source ID, start, end, explicit unit. Characters, seconds and
  pages are never silently converted. Adapters validate exclusion reasons.
- `Product`: directory, patterns, required/optional status, minimum size and
  preserve-existing publication policy.
- `Task`: stable ID, relative output path, input paths, metadata, required status.
  File hashes and metadata form the input fingerprint.
- `Report`: schema_version=1, tool, ok, issues. Issues contain code, message,
  path and severity. Warnings do not turn ok into false.

Domain adapters live in video2book's `src/core/production.py` and the other
tools' `src/<tool>/production.py`. Ingestion, prompts and provenance remain local.

## Task States and Compatibility

Exporters maintain `production_state.json` in the workspace:

- `pending`: output has not been written.
- `blocked`: a declared input is absent.
- `stale`: inputs changed, or re-export still has the unchanged old output.
- `ready`: inputs match and output exists; domain quality checks still apply.
- `unverified`: an existing legacy output was first encountered without a
  prior receipt. This warning is not proof of freshness.

A workspace without receipts reports `untracked`. Checks never write receipts
or migrate content. Re-exporting alone cannot approve a stale output. Rewrite
or review the output after re-export, then reassemble and run the domain gate.
Plan files are inputs: editing one conservatively invalidates all dependent
tasks, even if some sections are unchanged.

Video's dispatch queue may bind an initially missing transcript after it first
becomes available, before any article exists. This exception never accepts a
change to an input that was already present at export time.

All tools expose `check --status --json` with their existing workspace argument.
This read-only products-and-fingerprints report is not the full quality gate.
Video/wechat still use `check --production`; book/chat use `check`.
Missing optional chat notes/maps do not block delivery. Before writing them,
finish section articles and rerun `write-tasks` to bind the latest article hashes.

Fingerprints and size thresholds cannot prove factual fidelity. Content still
needs human or Agent review. Receipts are never published to courses repos.

## Assembly Policies

Shared code handles coverage, normalization and content-stable atomic file
writes. Ordering, chapter metadata and prompts remain domain-specific.
Video/book strip generated article headers; WeChat preserves author openings.
Chat retains topic order and speaker-attribution rules. Only derived textbook
files are removed during assembly, never sources or authored articles.

## Publication Policies

The local publisher performs domain validation, whitelisted staging, catalog
and index updates, and rollback on caught installation failures. An exclusive
repository lock serializes cooperating publishers. No remote Git operation
or reader deployment is performed. Domain adapters may prepare additional portable
assets inside the staged course; preparation failures never replace live content.

Video's adapter refuses writes to its read-only target; its transcript policy
preserves existing files. WeChat mirrors its products plus assets; book mirrors
books/notes/source chunks; chat notes/maps are optional. Required workspace
evidence and required published products are distinct rules.

Multi-file publication is not crash-atomic. A killed process may leave a lock
or .publish-* directory. Inspect active processes, metadata and recovery data
before removing a lock or restoring a backup. Failed exception rollback keeps
recovery data and reports its path. No destructive automatic recovery is attempted.
