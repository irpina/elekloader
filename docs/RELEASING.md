[elekloader docs](README.md) › Releasing

# Releasing

A release of elekloader is a GitHub release tagged `v` + elekloader's
version, carrying the core files. The workflows then build the apps and the
kit from it and attach them, and the web page takes its cores from the
latest release. Nothing from Elektron is ever attached: the cores are built
where the stock files are, and only the cores are uploaded.

## A full release (vX.Y.Z)

1. **The version.** Set it in `pyproject.toml`, `elekloader/__init__.py`,
   `js/src/version.ts` and `js/package.json`, and merge that to main.
2. **The cores.** From that commit, build each core with the SDK
   ([CORES.md](CORES.md#building-a-core)), one per device and OS with
   linkable mods, and lint each against its stock file. The SDK writes
   `core-<version>.elemod` (with `-os<OS>` for a port); rename each so the
   device is in its name, as the apps and the page expect:

   | built from | release file |
   |---|---|
   | `mods/core` | `core-<version>.elemod`, `core-<version>-os1.54.elemod` |
   | `mods/core-dn1` | `core-dn1-<version>.elemod`, `core-dn1-<version>-os1.44.elemod` |
   | `mods/core-dt2` | `core-dt2-<version>.elemod` |
   | `mods/core-ot` | `core-ot-<version>.elemod` |

   A release may carry several versions of one device's core (the Digitakt
   mk1's 2.1 and 3.0 lines, say): a build picks one ([CORES.md](CORES.md#how-a-build-picks-one)).

   The other mods (machine-pages, machines-dn1, dspbus-ot, digicosm-dn1) are not
   cores. The apps and the page take only `core-*.elemod` from a release; a mod
   reaches the shop from its own release (DigiCosm does, [WEB.md](WEB.md)).
   machine-pages, machines-dn1 and dspbus-ot are not in the shop yet.
3. **The release.** Create it on that commit with the core files attached:
   `gh release create vX.Y.Z core-*.elemod --target <commit>`.
4. **The apps.** Run **windows-build** and **macos-build** by hand (Actions >
   Run workflow) with the tag. Each takes the release's `core-*.elemod`,
   builds and self-tests its app, and attaches it with its line in
   `SHA256SUMS.txt`. The workflows check that the tag is `v` + the version at
   that commit. [APPS.md](APPS.md) has the details and macos-build's
   signing secrets.
5. **The kit.** Run **kit-build** with the tag. It attaches
   `elekloader-kit-<version>.zip` and `elekloader-catalog.json` (the feed of
   `web/catalog.json`, with the release's cores) with their checksums
   ([INTEGRATING.md](INTEGRATING.md)). Node is pinned, so the zip is the one
   `packaging/build_kit.py` gives on your machine with the same Node. With
   **test** ticked it builds the branch it is run on and keeps the two files
   as the run's artifact instead.
6. **The site.** The **pages** workflow runs on every push to main. A new
   release's cores reach the site on its next run, so run **pages** by hand
   after the release.

## Pre-releases

A pre-release is never the latest, so the apps and the page's own cores
stay the latest release's.

- **The kit alone (`kit-vX.Y.Z`):** kit-build builds the kit and the
  catalog with the latest release's cores. The version is still
  elekloader's at that tag, so a second kit pre-release needs a new version.
- **One device's core (`core-dn1-v2.3`, say):** a pre-release carrying that
  core's files and `SHA256SUMS.txt`, and items of kind `core` in
  `web/catalog.json` that point at it ([WEB.md](WEB.md)). The web page's shop
  and the kit's next catalog take the core from there. The next full
  release carries it as its own.

## The mod shop's list

`web/catalog.json` is edited by hand and merged like code: each item pins a
file of a GitHub release, or of a repository at a commit, by sha256
([WEB.md](WEB.md)). The next pages run puts it on the site.

## Rules

- **No firmware is ever attached.** That means no stock file, no build, no
  part of either. Only cores, apps, the kit, the catalog and checksums.
- **A file a release carries is never replaced by different bytes.** Sites
  pin the kit and the catalog by sha256; kit-build refuses to replace them.
  To rebuild one on purpose, delete it from the release first.
- Each workflow keeps the other workflows' lines in `SHA256SUMS.txt`.
