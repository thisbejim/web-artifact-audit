from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import os
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple, Union
from urllib.parse import unquote, urlsplit

from .models import AssetReference, Finding, ScanOptions, ScanResult


_URL_SCHEMES = {
    "http",
    "https",
    "data",
    "blob",
    "mailto",
    "tel",
    "javascript",
    "about",
    "ftp",
}
_TEXT_EXTENSIONS = {
    ".css",
    ".html",
    ".htm",
    ".js",
    ".mjs",
    ".cjs",
    ".json",
    ".map",
    ".webmanifest",
    ".svg",
    ".xml",
}
_RESOURCE_ATTRIBUTES = {
    "img": (("src", "image"), ("poster", "image"), ("srcset", "image-set")),
    "source": (("src", "media"), ("srcset", "media-set")),
    "video": (("src", "media"), ("poster", "image")),
    "audio": (("src", "media"),),
    "track": (("src", "media"),),
    "iframe": (("src", "document"),),
    "embed": (("src", "document"),),
    "object": (("data", "document"),),
    "script": (("src", "script"),),
}
_LINK_RELS = {
    "stylesheet": "stylesheet",
    "manifest": "manifest",
    "icon": "icon",
    "shortcut": "icon",
    "apple-touch-icon": "icon",
    "preload": "preload",
    "modulepreload": "module",
    "prefetch": "prefetch",
    "alternate": "alternate",
}
_CSS_URL_RE = re.compile(r"url\(\s*(?P<quote>[\"']?)(?P<url>.*?)(?P=quote)\s*\)", re.I | re.S)
_CSS_IMPORT_RE = re.compile(r"@import\s+(?P<quote>[\"'])(?P<url>.*?)(?P=quote)", re.I | re.S)
_SOURCEMAP_RE = re.compile(r"^\s*(?://|/\*)?\s*[#@]\s*sourceMappingURL\s*=\s*(\S+)", re.M)
_SRCSET_CANDIDATE_RE = re.compile(r"(?:data:[^\s]+|[^,\s]+)(?:\s+(?:\d+(?:\.\d+)?[wx]))?", re.I)
_JS_IMPORT_RE = re.compile(
    r"\b(?:import|export)\s*(?:\(\s*)?(?:[^\"'`\n;]*?\sfrom\s*)?[\"'](?P<url>[^\"'`]+)[\"']"
)
_JS_NEW_URL_RE = re.compile(
    r"\bnew\s+URL\(\s*[\"'](?P<url>[^\"']+)[\"']\s*,\s*import\.meta\.url"
)
_JS_IMPORT_SCRIPTS_RE = re.compile(r"\bimportScripts\s*\(\s*[\"'](?P<url>[^\"']+)[\"']")
_JS_PRECACHE_RE = re.compile(
    r"(?:precacheAndRoute|__WB_MANIFEST)\s*\(?(?:\s*\[)(?P<body>.*?)(?:\])",
    re.I | re.S,
)
_JS_STRING_RE = re.compile(r"[\"'](?P<url>[^\"']+)[\"']")
_DYNAMIC_IMPORT_RE = re.compile(r"\bimport\s*\(\s*(?![\"'`])")
_SRI_RE = re.compile(r"(?P<algorithm>sha256|sha384|sha512)-(?P<digest>[A-Za-z0-9+/=_-]+)")
_SRI_RANK = {"sha256": 1, "sha384": 2, "sha512": 3}
_SVG_URL_RE = re.compile(r"(?:href|xlink:href|src)\s*=\s*[\"'](?P<url>[^\"']+)[\"']", re.I)
_ASSET_MANIFEST_KEYS = {
    "file",
    "files",
    "url",
    "src",
    "assets",
    "entrypoints",
    "imports",
    "dynamicimports",
    "css",
}


def _is_external(target: str) -> bool:
    value = target.strip()
    if not value or value.startswith("#"):
        return True
    split = urlsplit(value)
    if split.scheme.lower() in _URL_SCHEMES or split.netloc:
        return True
    if value.startswith("//"):
        return True
    return False


def _strip_url(target: str) -> str:
    split = urlsplit(target.strip())
    return unquote(split.path)


def _split_srcset(value: str) -> Iterator[str]:
    """Yield URL candidates from a srcset without treating descriptors as URLs."""

    # A data URL may itself contain commas, so splitting blindly on commas can
    # turn the tail of an inline image into a fake local filename.
    for match in _SRCSET_CANDIDATE_RE.finditer(value):
        token = match.group(0).split()[0]
        if token:
            yield token


def _line_col(text: str, offset: int) -> Tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    return line, offset - last_newline


def _norm_relative(value: str) -> str:
    normalized = posixpath.normpath(value.replace("\\", "/"))
    if normalized == ".":
        return ""
    if normalized.startswith("./"):
        return normalized[2:]
    return normalized


class _HTMLReferenceParser(HTMLParser):
    def __init__(self, file: str, add_reference):
        super().__init__(convert_charrefs=False)
        self.file = file
        self.add_reference = add_reference
        self.base_href: Optional[str] = None
        self.in_style = False
        self.in_script = False
        self._style_chunks: List[str] = []
        self._script_chunks: List[str] = []
        self._style_start = 0
        self._script_start = 0

    def _location(self) -> Tuple[int, int]:
        line, column = self.getpos()
        return line, column + 1

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attr_map = {key.lower(): value for key, value in attrs if value is not None}
        line, column = self._location()
        if tag == "base" and attr_map.get("href") is not None:
            self.base_href = attr_map["href"]
        for attribute, kind in _RESOURCE_ATTRIBUTES.get(tag, ()):
            value = attr_map.get(attribute)
            if value is None:
                continue
            values = _split_srcset(value) if attribute == "srcset" else (value,)
            for target in values:
                self.add_reference(
                    AssetReference(
                        self.file,
                        line,
                        column,
                        target,
                        kind,
                        "html",
                        attr_map.get("integrity") if attribute == "src" else None,
                    ),
                    self.base_href,
                )
        if tag == "link":
            rels = set((attr_map.get("rel") or "").lower().split())
            for rel in rels:
                kind = _LINK_RELS.get(rel)
                if kind and attr_map.get("href") is not None:
                    self.add_reference(
                        AssetReference(
                            self.file,
                            line,
                            column,
                            attr_map["href"],
                            kind,
                            "html",
                            attr_map.get("integrity"),
                        ),
                        self.base_href,
                    )
                    break
        if "style" in attr_map:
            self.add_inline_css(attr_map["style"], line, column)
        if tag == "style":
            self.in_style = True
            self._style_chunks = []
            self._style_start = line
        if tag == "script":
            self.in_script = True
            self._script_chunks = []
            self._script_start = line

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() == "style":
            self.in_style = False
        if tag.lower() == "script":
            self.in_script = False

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "style" and self.in_style:
            self.add_inline_css("".join(self._style_chunks), self._style_start, 1)
            self.in_style = False
        if tag == "script" and self.in_script:
            self.add_inline_js("".join(self._script_chunks), self._script_start, 1)
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_style:
            self._style_chunks.append(data)
        if self.in_script:
            self._script_chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")

    def add_inline_css(self, text: str, line: int, column: int) -> None:
        for match in _CSS_URL_RE.finditer(text):
            target = match.group("url").strip()
            item_line, item_col = _line_col(text, match.start())
            self.add_reference(
                AssetReference(self.file, line + item_line - 1, column if item_line == 1 else item_col, target, "style", "html"),
                self.base_href,
            )

    def add_inline_js(self, text: str, line: int, column: int) -> None:
        for reference in _extract_js_references(self.file, text, line, column, "html"):
            self.add_reference(reference, self.base_href)


def _extract_js_references(file: str, text: str, start_line: int, start_column: int, source: str) -> Iterator[AssetReference]:
    seen: Set[Tuple[int, str, str]] = set()
    patterns = (
        (_JS_IMPORT_RE, "module"),
        (_JS_NEW_URL_RE, "module-asset"),
        (_JS_IMPORT_SCRIPTS_RE, "script"),
    )
    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            target = match.group("url")
            line, column = _line_col(text, match.start("url"))
            line += start_line - 1
            if line == start_line:
                column += start_column - 1
            key = (line, target, kind)
            if key not in seen:
                seen.add(key)
                yield AssetReference(file, line, column, target, kind, source)
    for match in _SOURCEMAP_RE.finditer(text):
        target = match.group(1).strip()
        line, column = _line_col(text, match.start(1))
        line += start_line - 1
        if line == start_line:
            column += start_column - 1
        key = (line, target, "source-map")
        if key not in seen:
            seen.add(key)
            yield AssetReference(file, line, column, target, "source-map", source)
    for match in _JS_PRECACHE_RE.finditer(text):
        body = match.group("body")
        for nested in _JS_STRING_RE.finditer(body):
            target = nested.group("url")
            if _is_external(target):
                continue
            offset = match.start("body") + nested.start("url")
            line, column = _line_col(text, offset)
            line += start_line - 1
            if line == start_line:
                column += start_column - 1
            key = (line, target, "precache")
            if key not in seen:
                seen.add(key)
                yield AssetReference(file, line, column, target, "precache", source)


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


class _Scanner:
    def __init__(self, root: Path, options: ScanOptions):
        self.root = root
        self.options = options
        self.result = ScanResult(root=root, options=options)
        self.file_paths: Dict[str, Path] = {}
        self.casefold_paths: Dict[str, List[str]] = {}
        self.checked_source_maps: Set[str] = set()
        self.checked_manifests: Set[str] = set()

    def add_finding(self, finding: Finding) -> None:
        self.result.findings.append(finding)

    def ignored(self, relative: str) -> bool:
        return any(fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(relative, pattern.lstrip("./")) for pattern in self.options.ignore)

    def collect_files(self) -> None:
        for directory, dirnames, filenames in os.walk(self.root, followlinks=False):
            kept_dirs: List[str] = []
            for name in sorted(dirnames):
                if name == ".git":
                    continue
                directory_path = Path(directory) / name
                if directory_path.is_symlink():
                    relative = directory_path.relative_to(self.root).as_posix()
                    self.add_finding(
                        Finding(
                            "WAA011",
                            "warning",
                            "symlink directory skipped; deployment behavior varies by host",
                            relative,
                            1,
                            1,
                            hint="copy the resolved files into the build output if they are required",
                        )
                    )
                    continue
                kept_dirs.append(name)
            dirnames[:] = kept_dirs
            for name in sorted(filenames):
                full = Path(directory) / name
                relative = full.relative_to(self.root).as_posix()
                if self.ignored(relative):
                    continue
                if full.is_symlink():
                    self.add_finding(
                        Finding(
                            "WAA011",
                            "warning",
                            "symlink skipped; deployment behavior varies by host",
                            relative,
                            1,
                            1,
                            hint="copy the resolved file into the build output if it is required",
                        )
                    )
                    continue
                try:
                    size = full.stat().st_size
                except OSError as exc:
                    self.add_finding(Finding("WAA012", "error", f"cannot stat artifact: {exc}", relative, 1, 1))
                    continue
                self.file_paths[relative] = full
                self.casefold_paths.setdefault(relative.casefold(), []).append(relative)
                self.result.files.append(relative)
                self.result.bytes_scanned += size
        self.result.files.sort()

    def add_reference(self, reference: AssetReference, base_href: Optional[str] = None) -> None:
        self.result.references.append(reference)
        if _is_external(reference.target):
            self.result.external_references += 1
            return
        # Browser module resolution treats a specifier without ./, ../, or /
        # as a package/import-map name. It is not a file that should be present
        # in a static output directory; bundled output normally rewrites it.
        if reference.kind == "module" and not reference.target.strip().startswith((".", "/")):
            self.result.external_references += 1
            return
        candidate, bypasses_base, escaped = self.resolve(reference.file, reference.target, base_href)
        if escaped:
            self.add_finding(
                Finding(
                    "WAA005",
                    "error",
                    f"reference escapes the artifact root: {reference.target!r}",
                    reference.file,
                    reference.line,
                    reference.column,
                    reference.target,
                    "keep local references inside the published output",
                )
            )
            return
        if bypasses_base:
            self.add_finding(
                Finding(
                    "WAA004",
                    "error",
                    f"root-relative reference bypasses deployment base path {self.options.normalized_base_path()!r}",
                    reference.file,
                    reference.line,
                    reference.column,
                    reference.target,
                    f"use a relative URL or include the base path in {reference.target!r}",
                )
            )
        if candidate is None:
            return
        exact = self.file_paths.get(candidate)
        if exact is None:
            case_matches = self.casefold_paths.get(candidate.casefold(), []) if self.options.check_case else []
            if len(case_matches) == 1:
                self.add_finding(
                    Finding(
                        "WAA002",
                        "error",
                        f"case mismatch: {reference.target!r} resolves to {candidate!r}, found {case_matches[0]!r}",
                        reference.file,
                        reference.line,
                        reference.column,
                        reference.target,
                        "make the URL casing match the emitted filename exactly",
                    )
                )
                return
            if len(case_matches) > 1:
                self.add_finding(
                    Finding(
                        "WAA009",
                        "error",
                        f"ambiguous case-insensitive match for {candidate!r}: {', '.join(case_matches)}",
                        reference.file,
                        reference.line,
                        reference.column,
                        reference.target,
                    )
                )
                return
            if candidate.endswith("/"):
                candidate = candidate.rstrip("/")
            index_candidate = f"{candidate}/index.html" if candidate else "index.html"
            if index_candidate in self.file_paths:
                return
            self.add_finding(
                Finding(
                    "WAA001",
                    "error",
                    f"missing {reference.kind} {reference.target!r} (resolved path {candidate!r})",
                    reference.file,
                    reference.line,
                    reference.column,
                    reference.target,
                    "check the build output name and the URL emitted by the bundler",
                )
            )
            return
        if self.options.check_sri and reference.integrity:
            self.check_sri(reference, exact)
        if reference.kind == "source-map":
            self.check_source_map(reference, exact)
        if reference.kind == "manifest":
            self.check_manifest(reference, exact)

    def resolve(self, source_file: str, target: str, base_href: Optional[str]) -> Tuple[Optional[str], bool, bool]:
        raw = _strip_url(target)
        if not raw:
            return None, False, False
        base_path = self.options.normalized_base_path()
        bypasses_base = False
        if raw.startswith("/"):
            root_target = _norm_relative(raw.lstrip("/"))
            if base_path != "/" and root_target and not (root_target + "/").startswith(base_path.lstrip("/")):
                bypasses_base = True
            if base_path != "/" and (root_target == base_path.strip("/") or root_target.startswith(base_path.lstrip("/"))):
                root_target = root_target[len(base_path.lstrip("/")) :].lstrip("/")
            candidate = root_target
        else:
            source_dir = posixpath.dirname(source_file)
            if base_href:
                if _is_external(base_href):
                    return None, False, False
                base_raw = _strip_url(base_href)
                if base_raw.startswith("/"):
                    base_dir = _norm_relative(base_raw.lstrip("/"))
                    deployment_prefix = base_path.strip("/")
                    if deployment_prefix and (base_dir == deployment_prefix or base_dir.startswith(deployment_prefix + "/")):
                        source_dir = base_dir[len(deployment_prefix) :].lstrip("/")
                    else:
                        source_dir = base_dir
                else:
                    source_dir = _norm_relative(posixpath.join(source_dir, base_raw))
                    if not base_raw.endswith("/"):
                        source_dir = posixpath.dirname(source_dir)
            candidate = _norm_relative(posixpath.join(source_dir, raw))
        escaped = candidate == ".." or candidate.startswith("../")
        return candidate, bypasses_base, escaped

    def check_sri(self, reference: AssetReference, path: Path) -> None:
        tokens = list(_SRI_RE.finditer(reference.integrity or ""))
        if not tokens:
            self.add_finding(
                Finding("WAA010", "error", "integrity attribute has no supported sha256/sha384/sha512 hash", reference.file, reference.line, reference.column, reference.target, "use a base64-encoded SRI digest")
            )
            return
        strongest = max(_SRI_RANK[token.group("algorithm")] for token in tokens)
        try:
            content = path.read_bytes()
        except OSError as exc:
            self.add_finding(Finding("WAA013", "error", f"cannot read local resource for integrity check: {exc}", reference.file, reference.line, reference.column, reference.target))
            return
        matched = False
        for token in tokens:
            algorithm = token.group("algorithm")
            if _SRI_RANK[algorithm] != strongest:
                continue
            digest = base64.b64encode(hashlib.new(algorithm, content).digest()).decode("ascii")
            expected = token.group("digest").replace("-", "+").replace("_", "/")
            expected += "=" * ((4 - len(expected) % 4) % 4)
            if digest == expected:
                matched = True
                break
        if not matched:
            self.add_finding(
                Finding("WAA003", "error", f"SRI hash does not match local {reference.target!r}", reference.file, reference.line, reference.column, reference.target, "regenerate the integrity attribute after the final build step")
            )

    def check_source_map(self, reference: AssetReference, path: Path) -> None:
        relative = self.relative_for_path(path) or reference.target
        self.checked_source_maps.add(relative)
        text = _read_text(path)
        if text is None:
            self.add_finding(Finding("WAA013", "error", "source map is not valid UTF-8 JSON", reference.file, reference.line, reference.column, reference.target, "emit a valid .map file or remove the sourceMappingURL comment"))
            return
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            self.add_finding(Finding("WAA013", "error", f"source map is invalid JSON: {exc.msg}", reference.file, reference.line, reference.column, reference.target, "regenerate the source map"))
            return
        if not isinstance(document, dict) or not isinstance(document.get("version"), int) or not isinstance(document.get("sources"), list):
            self.add_finding(Finding("WAA013", "error", "source map must contain an integer version and sources array", reference.file, reference.line, reference.column, reference.target, "regenerate the source map with a standard source-map writer"))

    def check_manifest(self, reference: AssetReference, path: Path) -> None:
        relative = self.relative_for_path(path) or reference.target
        self.checked_manifests.add(relative)
        text = _read_text(path)
        if text is None:
            self.add_finding(Finding("WAA014", "error", "web manifest is not valid UTF-8 JSON", reference.file, reference.line, reference.column, reference.target))
            return
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            self.add_finding(Finding("WAA014", "error", f"web manifest is invalid JSON: {exc.msg}", reference.file, reference.line, reference.column, reference.target, "regenerate or validate manifest JSON"))
            return
        if not isinstance(document, dict):
            self.add_finding(Finding("WAA014", "error", "web manifest root must be an object", reference.file, reference.line, reference.column, reference.target))
            return
        for icon in document.get("icons", []) if isinstance(document.get("icons"), list) else []:
            if isinstance(icon, dict) and isinstance(icon.get("src"), str):
                self.add_reference(AssetReference(relative, 1, 1, icon["src"], "manifest-icon", "manifest"), None)
        if isinstance(document.get("start_url"), str):
            self.add_reference(AssetReference(relative, 1, 1, document["start_url"], "manifest-start", "manifest"), None)

    def relative_for_path(self, path: Path) -> Optional[str]:
        for relative, candidate in self.file_paths.items():
            if candidate == path:
                return relative
        return None

    def parse_file(self, relative: str, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix not in _TEXT_EXTENSIONS:
            return
        text = _read_text(path)
        if text is None:
            return
        if suffix in {".html", ".htm"}:
            parser = _HTMLReferenceParser(relative, self.add_reference)
            try:
                parser.feed(text)
                parser.close()
            except Exception as exc:  # HTMLParser is intentionally permissive; surface unexpected parser failures.
                self.add_finding(Finding("WAA015", "warning", f"could not parse HTML: {exc}", relative, 1, 1))
            return
        if suffix == ".css":
            for match in _CSS_URL_RE.finditer(text):
                line, column = _line_col(text, match.start("url"))
                self.add_reference(AssetReference(relative, line, column, match.group("url").strip(), "style", "css"), None)
            for match in _CSS_IMPORT_RE.finditer(text):
                line, column = _line_col(text, match.start("url"))
                self.add_reference(AssetReference(relative, line, column, match.group("url").strip(), "stylesheet", "css"), None)
            return
        if suffix == ".svg":
            for match in _SVG_URL_RE.finditer(text):
                line, column = _line_col(text, match.start("url"))
                self.add_reference(AssetReference(relative, line, column, match.group("url"), "svg-resource", "svg"), None)
            return
        if suffix in {".js", ".mjs", ".cjs"}:
            dynamic = _DYNAMIC_IMPORT_RE.search(text)
            if dynamic:
                line, column = _line_col(text, dynamic.start())
                severity = "error" if self.options.strict else "warning"
                hint = "use a literal asset path or add a deliberate ignore rule" if self.options.strict else "run with --strict to make unresolved dynamic imports fail CI"
                self.add_finding(Finding("WAA006", severity, "dynamic import expression cannot be resolved statically", relative, line, column, hint=hint))
            for reference in _extract_js_references(relative, text, 1, 1, "js"):
                self.add_reference(reference, None)
            return
        if suffix in {".json", ".webmanifest", ".map"}:
            # JSON manifests are discovered through HTML references. Parse standalone
            # import maps and service-worker manifests only when their shape is known.
            if suffix == ".map" and relative in self.checked_source_maps:
                return
            if suffix == ".webmanifest" and relative in self.checked_manifests:
                return
            try:
                document = json.loads(text)
            except json.JSONDecodeError:
                if suffix == ".map":
                    self.add_finding(Finding("WAA013", "error", "source map is invalid JSON", relative, 1, 1, hint="regenerate the source map"))
                    self.checked_source_maps.add(relative)
                elif suffix == ".webmanifest":
                    self.add_finding(Finding("WAA014", "error", "web manifest is invalid JSON", relative, 1, 1, hint="regenerate or validate manifest JSON"))
                    self.checked_manifests.add(relative)
                return
            if suffix == ".webmanifest" and isinstance(document, dict):
                self.checked_manifests.add(relative)
                for icon in document.get("icons", []) if isinstance(document.get("icons"), list) else []:
                    if isinstance(icon, dict) and isinstance(icon.get("src"), str):
                        self.add_reference(AssetReference(relative, 1, 1, icon["src"], "manifest-icon", "manifest"), None)
                if isinstance(document.get("start_url"), str):
                    self.add_reference(AssetReference(relative, 1, 1, document["start_url"], "manifest-start", "manifest"), None)
            if suffix == ".json" and "manifest" in path.name.lower():
                for target, line in _asset_manifest_targets(document):
                    self.add_reference(AssetReference(relative, line, 1, target, "asset-manifest", "json"), None)
            if isinstance(document, dict) and ("imports" in document or "scopes" in document):
                for target, line in _import_map_targets(document):
                    self.add_reference(AssetReference(relative, line, 1, target, "import-map", "json"), None)

    def run(self) -> ScanResult:
        self.collect_files()
        for relative in self.result.files:
            self.parse_file(relative, self.file_paths[relative])
        self.result.sort_findings()
        return self.result


def _import_map_targets(document: object) -> Iterator[Tuple[str, int]]:
    def walk(value: object, active: bool) -> Iterator[str]:
        if isinstance(value, dict):
            for key, child in value.items():
                yield from walk(child, active or key in {"imports", "scopes"})
        elif isinstance(value, list):
            for child in value:
                yield from walk(child, active)
        elif active and isinstance(value, str) and not _is_external(value) and (value.startswith(".") or value.startswith("/")):
            yield value

    for target in walk(document, False):
        yield target, 1


def _asset_manifest_targets(document: object) -> Iterator[Tuple[str, int]]:
    """Extract path-like values from common bundler asset manifests."""

    def walk(value: object, active: bool) -> Iterator[str]:
        if isinstance(value, dict):
            for key, child in value.items():
                yield from walk(child, active or key.lower() in _ASSET_MANIFEST_KEYS)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child, active)
        elif active and isinstance(value, str) and not _is_external(value):
            if value.startswith((".", "/")) or "/" in value or posixpath.splitext(value)[1]:
                yield value

    for target in walk(document, False):
        yield target, 1


def scan(path: Union[str, Path], options: Optional[ScanOptions] = None) -> ScanResult:
    """Scan *path* and return deterministic findings without executing anything."""

    root = Path(path).expanduser().resolve()
    policy = options or ScanOptions()
    if not root.exists():
        result = ScanResult(root=root, options=policy)
        result.findings.append(Finding("WAA100", "error", "artifact directory does not exist", str(path), 1, 1, hint="run the audit after the build step"))
        return result
    if not root.is_dir():
        result = ScanResult(root=root, options=policy)
        result.findings.append(Finding("WAA101", "error", "artifact path is not a directory", str(path), 1, 1))
        return result
    return _Scanner(root, policy).run()
