# Releases

`.github/workflows/release.yml` publishes a GitHub release for every pushed `v*.*.*` tag:
the Claude Desktop bundle `sdpm.mcpb` and, for stable tags, six release manifests.

## Tag policy

- **Release tags are cut from `main`.** The workflow refuses a tag whose commit is not on
  `main`; delete such a tag and tag a commit on `main`. Installs ignore it anyway: `sdpm
  update` only moves to stable tags that are ancestors of `origin/main`, because a later
  release from `main` would never contain a commit made on a branch.
- **Stable tags are `vX.Y.Z`** (no leading zeros). Anything else (`v0.13.0-rc.1`) is published
  as a pre-release without manifests, never becomes "latest", and no install moves to it.
- **A published stable tag is never moved, deleted or reused.** A bad release is replaced by
  the next patch release. The `sdpm` command since 0.13.0 fetches tags with
  `+refs/tags/*:refs/tags/*` and `--prune`, so it would follow a moved or deleted tag, but
  the 0.12 commands (#529, #532) fetch with `--tags --prune origin main`, which refuses a
  moved tag (`! [rejected] … (would clobber existing tag)`) and stops their update.
- `__version__` in `sdpm/sdpm/__init__.py` must equal the tag (without `v`); the manifest
  step fails otherwise.

## Release manifests

`manifest.py` writes `release-{macos,linux,windows}-{install,update}.json` from
`manifest.toml` (the minimum launcher, and per OS the tools a release needs with their install
hints) and the release's "Local installs" bullets in `CHANGELOG.md`. Every file is checked
with the parser that reads it (`servers/local/checkout_update.py`, `parse_manifest`).

```bash
uv run --no-project --python ">=3.11" python scripts/release/manifest.py --tag v0.13.0 --out dist/manifests
```

Each install and `sdpm update` on the release channel downloads exactly one of them: the
manifest of the newest release, for its OS, `install` for a new checkout and `update` for
everything else (including the installer run over an existing install, and the first update
of a pre-0.13 command). The manifest can only hold an install back (a tool too old, a commit
that does not match the tag); it never picks a target. A release without manifests, or a
fetch that fails, falls back to the git tags. The main channel downloads none.

To correct a manifest, fix `manifest.toml` (or the CHANGELOG) on `main` and re-run the
workflow for the tag: `gh release upload --clobber` replaces the assets. A replaced asset is
a new asset, so its `download_count` starts again at 0.

## Counting installs and updates

GitHub counts every download of a release asset. The manifests are downloaded once per
install or update, so their counts are the number of installs and updates per release and
OS. Nothing else is sent.

```bash
gh api repos/aws-samples/sample-spec-driven-presentation-maker/releases --paginate \
  --jq '.[] | {tag: .tag_name, assets: [.assets[] | select(.name | startswith("release-")) | {name, download_count}]}'
```

- The counts are cumulative; record them periodically to see a trend (not automated yet).
- CI downloads some too: every run of the `release-channel` job in `installer.yml` probes the
  newest real release once per OS (`release-<os>-update.json`, three per run). Subtract that
  job's run count. The other installer jobs follow `main` and download none.
- Main-channel installs and updates are not counted, and a pre-0.13 `sdpm` command is
  counted from its first update (which runs the new code).
