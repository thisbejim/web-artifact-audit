# Product specification

## Target user

The primary user is a frontend or documentation engineer who publishes a static build from Vite, Astro, Next export, SvelteKit, a docs generator, or a hand-written site. The secondary user is the maintainer of a CI pipeline that wants a fast, dependency-free release gate.

## Problem

The source tree and local dev server can be healthy while the final directory shipped to a static host has a missing or mis-resolved resource. Common causes include hashed chunks not copied, CSS URLs resolved from the wrong directory, case differences hidden by a case-insensitive filesystem, a project-site base path, stale source maps, and integrity attributes left over from a previous build.

## Current workaround and why it is inadequate

Teams open a preview in a browser, inspect the Network panel, or run a link crawler. Those approaches require a server (and often a browser), miss resources only discovered by CSS/JavaScript, are awkward in a post-build CI step, and cannot prove that a local SRI digest matches the exact bytes being published. Framework-specific base-path settings solve generation but do not verify an already-produced artifact.

## Core use case

After `npm run build` (or any equivalent), run:

```console
web-artifact-audit dist --base-path /docs/ --format sarif
```

The command walks the output, extracts browser-facing local references, resolves each one against the containing file and deployment prefix, and emits deterministic findings. A successful run is a release proof that all statically discoverable local resources exist with the expected casing and integrity.

## Non-goals

- It is not a browser, HTML validator, accessibility checker, SEO crawler, or uptime monitor.
- It does not fetch external URLs or evaluate JavaScript.
- It does not guess the result of arbitrary runtime string concatenation. Such imports are reported as warnings or strict errors.
- It does not rewrite an artifact or mutate source files.

## Interface

### Inputs

- One artifact directory (default `dist`).
- Optional deployment prefix (`--base-path`), ignore globs, and strictness/output flags.

### Outputs

- Human-readable text with stable rule code, path, line, and hint.
- JSON with a summary and reference inventory.
- SARIF 2.1.0 for code-scanning viewers.

### Errors and exit status

- `0`: no errors.
- `1`: one or more blocking findings.
- `2`: command-line/path usage error from `argparse`.

## Architecture

The implementation is a Python standard-library package:

1. `collect_files` walks regular files beneath the root without following symlinks and builds exact/case-folded indexes.
2. Format-specific extractors (`HTMLParser`, CSS/JS regular expressions, and JSON shape checks) produce `AssetReference` records with source locations.
3. One resolver applies URL semantics, base-path policy, URL decoding, traversal protection, and directory index fallback.
4. Validators check existence, case, SRI bytes, source-map JSON, and manifest JSON.
5. A stable `Finding` model feeds text, JSON, or SARIF renderers.

No network, process execution, optional runtime, or mutable global state is needed.

## Validation plan

The test suite covers:

- HTML, CSS, module, `srcset`, manifest, and source-map happy paths.
- Missing resources, wrong casing, traversal, invalid JSON, and SRI mismatch.
- Base-path mistakes and dynamic imports in warning and strict modes.
- Deterministic summary shape and the checked-in clean/broken fixtures.

The CI workflow runs the tests and `compileall` across Python 3.9–3.13.

## Differentiator

The unit of analysis is the *published artifact*, not the source project or a live URL. It combines browser-like local resolution with build-specific evidence (emitted chunk imports, CSS URLs, source maps, manifests, SRI, casing, and deployment prefixes) in a zero-network command that can be inserted directly after any build.
