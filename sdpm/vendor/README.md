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
| `revealjs/plugin/notes.js` | `dist/plugin/notes.js` | speaker view (`S`), global `RevealNotes` |
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

Then update the version in `THIRD-PARTY-LICENSES` and run
`SDPM_AUTO_INSTALL_ASSETS=0 uv run pytest tests/test_html_assemble.py` from the repository
root. Nothing else is generated from these files.
