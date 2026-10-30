# Vendored third-party files

HTML decks (`deck.json` `"outputFormat": "html"`) are assembled into one offline
`output.html`: every script and stylesheet is inlined, nothing is fetched from a CDN.
The files below are copied verbatim from the published npm package so the assembler
(`sdpm.engine.html.assemble`) can inline them without a network or a Node.js build.

## reveal.js — `revealjs/`

- Project: https://github.com/hakimel/reveal.js
- Version: see `revealjs/VERSION`
- License: MIT — `revealjs/LICENSE` (Copyright (C) 2011-2026 Hakim El Hattab, http://hakim.se,
  and reveal.js contributors). Also listed in the repository's `THIRD-PARTY-LICENSES`.

| File | From the npm package | Used for |
|---|---|---|
| `revealjs/reveal.js` | `dist/reveal.js` | presentation runtime (UMD, global `Reveal`) |
| `revealjs/reveal.css` | `dist/reveal.css` | core layout CSS (no theme) |
| `revealjs/reset.css` | `dist/reset.css` | CSS reset reveal.js expects |
| `revealjs/plugin/notes.js` | `dist/plugin/notes.js` | speaker view (`S`), global `RevealNotes`; bundles marked (MIT), listed in `THIRD-PARTY-LICENSES` |
| `revealjs/LICENSE` | `LICENSE` | license text |

The directory is deliberately not named `dist/` (the repository `.gitignore` ignores
every `dist/` directory).

### Updating

```bash
tmp=$(mktemp -d) && cd "$tmp"
npm pack reveal.js@6            # or the next major, after checking its changelog
tar xzf reveal.js-*.tgz
dest=<repo>/sdpm/vendor/revealjs
cp package/dist/reveal.js package/dist/reveal.css package/dist/reset.css package/LICENSE "$dest/"
cp package/dist/plugin/notes.js "$dest/plugin/"
node -p "require('./package/package.json').version" > "$dest/VERSION"
```

Then update the reveal.js version and the bundled marked major (reveal.js's `marked` devDependency) in
`THIRD-PARTY-LICENSES`, and run
`SDPM_AUTO_INSTALL_ASSETS=0 uv run pytest tests/test_html_assemble.py` from the repository
root. Nothing else is generated from these files.

## Apache ECharts — `echarts/`

- Project: https://github.com/apache/echarts
- Version: see `echarts/VERSION`
- License: Apache-2.0 — `echarts/LICENSE` and `echarts/NOTICE`; ECharts includes parts of d3
  under BSD-3-Clause (`echarts/licenses/LICENSE-d3`). Also listed in the repository's
  `THIRD-PARTY-LICENSES`.

Embedded only into decks whose slides declare it (`<section data-libs="echarts">`), once
per deck, preceded by a `/*! … */` comment holding `LICENSE`, `NOTICE` and `LICENSE-d3`.

| File | From the npm package | Used for |
|---|---|---|
| `echarts/echarts.min.js` | `dist/echarts.min.js` | chart library (UMD, global `echarts`) |
| `echarts/LICENSE` | `LICENSE` | license text |
| `echarts/NOTICE` | `NOTICE` | Apache-2.0 NOTICE (must accompany every copy) |
| `echarts/licenses/LICENSE-d3` | `licenses/LICENSE-d3` | license of the d3 parts ECharts includes |

### Updating

```bash
tmp=$(mktemp -d) && cd "$tmp"
npm pack echarts@6
tar xzf echarts-*.tgz
dest=<repo>/sdpm/vendor/echarts
cp package/dist/echarts.min.js package/LICENSE package/NOTICE "$dest/"
cp package/licenses/LICENSE-d3 "$dest/licenses/"
node -p "require('./package/package.json').version" > "$dest/VERSION"
```

## D3 — `d3/`

- Project: https://github.com/d3/d3
- Version: see `d3/VERSION`
- License: ISC — `d3/LICENSE` (Copyright 2010-2023 Mike Bostock). Also listed in the
  repository's `THIRD-PARTY-LICENSES`.

Embedded only into decks whose slides declare it (`<section data-libs="d3">`), once per
deck, preceded by a `/*! … */` comment holding `LICENSE`.

`d3.csvParse`, `d3.tsvParse` and `d3.dsvFormat(…).parse` build their row parser with
`new Function`, which needs `eval` and fails under the deck CSP (`d3.csvParseRows` and the
other `*Rows` functions do not).

| File | From the npm package | Used for |
|---|---|---|
| `d3/d3.min.js` | `dist/d3.min.js` | visualization library (UMD, global `d3`) |
| `d3/LICENSE` | `LICENSE` | license text |

### Updating

```bash
tmp=$(mktemp -d) && cd "$tmp"
npm pack d3@7
tar xzf d3-*.tgz
dest=<repo>/sdpm/vendor/d3
cp package/dist/d3.min.js package/LICENSE "$dest/"
node -p "require('./package/package.json').version" > "$dest/VERSION"
```

After updating either library, update its version in `THIRD-PARTY-LICENSES` and run
`SDPM_AUTO_INSTALL_ASSETS=0 uv run pytest tests/test_html_assemble.py tests/test_html_csp.py`
from the repository root.
