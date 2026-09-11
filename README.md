# web-artifact-audit

Offline release checks for a static web build directory.

`web-artifact-audit` catches the small path mistakes that make a production site load blank: a hashed chunk that was not emitted, a CSS background image with the wrong `../`, a filename whose casing only works on macOS, a project-site URL that bypasses `/docs/`, a stale source map, or an SRI digest copied from an earlier build.

It reads the finished artifact and reports file-and-line diagnostics. It does not start a server, launch a browser, contact a URL, require Docker, upload files, or execute JavaScript.

## Quick start

Run directly from a checkout (no installation or network access required):

```console
$ PYTHONPATH=src python -m web_artifact_audit fixtures/clean-site
PASS web-artifact-audit — 0 errors, 0 warnings
Scanned 4 files (… bytes) and checked 4 local references.
```

Install the command in a virtual environment or user site:

```console
python -m pip install .
web-artifact-audit path/to/dist
```

For a GitHub Pages project site, model the published subpath:

```console
web-artifact-audit dist --base-path /my-repository/
```

The command exits `0` when no errors are found and `1` when the artifact fails a check. Warnings (for example, an unresolved dynamic import) remain non-blocking unless `--strict` is used.

## A useful failure message

```console
$ web-artifact-audit fixtures/broken-site
FAIL web-artifact-audit — 3 errors, 0 warnings
Scanned 2 files (… bytes) and checked 4 local references.
ERROR   WAA001 index.html:5:… — missing script 'assets/app-9a2.js' (resolved path 'assets/app-9a2.js')
         hint: check the build output name and the URL emitted by the bundler
ERROR   WAA001 styles/site.css:1:… — missing style '../images/missing-texture.png' (resolved path 'images/missing-texture.png')
         hint: check the build output name and the URL emitted by the bundler
```

Every finding has a stable code, source path, line, and a fix hint so it can be used in a pre-publish hook or CI log.

## What it checks

- HTML resource attributes (`script`, `img`, `source`, `video`, `audio`, `iframe`, `object`), `srcset`, inline styles, and resource `<link>` elements.
- CSS `url(...)` and quoted `@import` references.
- JavaScript literal imports, `new URL("…", import.meta.url)`, `importScripts`, Workbox-style precache arrays, and `sourceMappingURL` comments.
- SVG `href`/`xlink:href` resources, web-manifest icons and `start_url`, common bundler `asset-manifest.json` entries, plus local entries in import maps.
- Browser-like relative URL resolution, query/fragment stripping, URL decoding, `..` escapes, directory `index.html` fallbacks, and optional deployment base paths.
- Exact filename casing (including a useful “found with different case” message), local SRI hashes (`sha256`, `sha384`, `sha512`), and source-map/manifest JSON shape.
- Text, JSON, and SARIF output for humans and automation.

External URLs, `data:`, `blob:`, fragments, and bare JavaScript package specifiers are intentionally skipped. The scan is local and deterministic; `--strict` turns statically unresolved dynamic imports into errors.

## Command reference

```text
web-artifact-audit [PATH] [options]

PATH                         artifact directory (default: dist)
--base-path /docs/            deployment prefix for root-relative references
--format text|json|sarif      report format (default: text)
--strict                      fail on unresolved dynamic imports
--ignore GLOB                 ignore a path; repeatable
--no-sri                      skip local integrity verification
--no-case-check               skip case checks
--version                     print the version
```

JSON contains `summary`, `findings`, and the discovered `references`. SARIF locations use artifact-relative URIs, making the report consumable by GitHub code scanning and other CI viewers:

```console
web-artifact-audit dist --format sarif > artifact.sarif
```

## Platforms and dependencies

Python 3.9+ is supported on macOS, Linux, and Windows. The scanner itself uses only the Python standard library. The repository includes a tiny in-tree build backend, so `python -m pip install .` does not need to download setuptools or any other build dependency.

## Why this exists

Static output is an awkward boundary: a dev server and a source tree can hide mistakes that only appear after a bundler renames, moves, or prefixes files. Existing link crawlers are useful for checking a running site or HTML links, but they do not provide a no-server build gate that understands CSS URLs, emitted chunks, source maps, manifests, base paths, and local SRI together. This tool is intentionally small and offline so it can run immediately after any framework’s build command.

The research and product decision are recorded in [`docs/research.md`](docs/research.md); the full product spec is in [`docs/design.md`](docs/design.md).

## CI

The repository’s workflow runs the standard-library test suite on Python 3.9–3.13, compiles the package, and performs a clean-artifact smoke check. A project can add one step after its build:

```yaml
- run: python -m pip install .
- run: npm run build
- run: web-artifact-audit dist --base-path "${{ vars.SITE_BASE_PATH || '/' }}" --format sarif > artifact.sarif
```

## Security and privacy

The scanner only opens files beneath the supplied artifact directory. It never sends file contents anywhere, evaluates JavaScript, follows symlinks, or contacts external URLs. It does not print file contents or secret values. Treat reports as potentially sensitive because filenames can reveal project structure.

## License

MIT. See [`LICENSE`](LICENSE).
