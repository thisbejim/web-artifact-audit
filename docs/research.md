# Opportunity research and selection

Research date: 2026-09-12. Scores are 0–10; higher is better. “Competition” is a penalty where an established project already solves the core problem.

| Candidate | Pain / frequency | Audience | Demand evidence | OSS advantage | Feasibility | Competition penalty | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Source-map validator | 8 | 8 | 8 | 6 | 8 | -9 | Reject: `jkup/source-map-validator` already offers comprehensive ECMA-426 validation. |
| MCP config linter | 9 | 7 | 8 | 8 | 7 | -9 | Reject: `ctxlint`, `mcp-audit`, and `mcplint` cover the static-lint niche. |
| SBOM diff gate | 8 | 8 | 8 | 7 | 7 | -9 | Reject: SBOMDiff and CycloneDX utilities already provide the central diff. |
| Docker context simulator | 9 | 8 | 9 | 9 | 8 | -10 | Reject: `docker-build-context` now directly lists/explains the real BuildKit context. |
| HAR redaction CLI | 8 | 7 | 7 | 7 | 7 | -7 | Reject: Google’s har-sanitizer and newer capture tools already redact HARs. |
| Static build-artifact reference audit | 9 | 9 | 9 | 9 | 8 | -5 | **Select**: existing crawlers validate live/HTML links, but no small offline release gate combines build-output resolution, base paths, CSS/JS references, SRI, maps, manifests, and casing. |

## Evidence for the selected problem

- GitHub’s [Pages troubleshooting guide](https://docs.github.com/en/pages/getting-started-with-github-pages/troubleshooting-404-errors-for-github-pages-sites) treats missing CSS, JavaScript, and image files as a recurring deployment failure mode.
- A recent [GitHub Pages discussion](https://github.com/orgs/community/discussions/188844) shows root-absolute URLs bypassing a repository project path and producing 404s.
- Vite users continue to report [asset failures under repository subpaths](https://github.com/vitejs/vite/issues/15488), and a recent [Vite issue](https://github.com/vitejs/vite/issues/22093) records deployment-specific broken asset URLs.
- A concrete post-build example explains why a [static site can work locally but break under a GitHub repository path](https://bfzli.com/deploying-a-static-site-breaks-asset-urls-under-a-repository-path).
- [Subresource Integrity](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Subresource_Integrity) makes the bytes/hash relationship a browser-enforced contract; checking it against the final local artifact is deterministic and privacy-preserving.

## Alternatives checked

- [HTMLProofer](https://github.com/gjtorikian/html-proofer) is a mature Ruby checker for rendered HTML, links, images, scripts, and optional SRI. It is broader on document-quality checks but is server-oriented and does not model emitted JS imports or a post-build deployment prefix as a single offline artifact contract.
- [Linkinator](https://github.com/JustinBeckwith/linkinator) crawls live or local files and can check CSS URLs. It is an excellent crawler, but it intentionally follows server/link behavior and does not provide this tool’s source-map, manifest, SRI-byte, casing, and base-path diagnostics together.
- [hyperlink](https://github.com/untitaker/hyperlink) is a fast static HTML link checker; its documentation explicitly limits the checker to HTML links rather than CSS resource graphs.
- [AssetGraph](https://github.com/assetgraph/assetgraph) can build rich dependency graphs and transform assets, but it is a framework for Node projects, not a tiny read-only CI gate for an already-built directory.

These tools remain useful complements. The selected project narrows the contract to “will the exact files in this output directory resolve as the browser will request them?”

## Why open source and standalone

The input is local build output, so a network service would add privacy and supply-chain risk without adding signal. A permissive, dependency-free implementation makes it easy to run in any language ecosystem’s CI and to extend with new deterministic extractors. The report is inspectable, reproducible, and safe to run on proprietary artifacts.
