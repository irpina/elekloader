[elekloader docs](README.md) › The apps

# The apps

How the Windows and macOS apps are built. To install one, see
[INSTALL.md](INSTALL.md); for when the workflows run in a release, see
[RELEASING.md](RELEASING.md).

## The Windows app

`packaging/build_windows.py --core core-2.1.elemod [core-dn1-2.0a.elemod ...]` builds
`elekloader.exe` with PyInstaller (`packaging/requirements-build.txt`). The
exe carries the cores in `elekloader/bundled`. The script checks the exe with
its `--selftest` (the version, Tk, the built-in cores and their hashes, the
devices it supports), then writes `elekloader-<version>-windows.exe` and
`SHA256SUMS.txt`.

The **windows-build** workflow (Actions, run by hand with a release's tag)
does the same on GitHub's Windows runner. It takes every `core*.elemod` from that
release and attaches the exe and `SHA256SUMS.txt` to it. core is built where
the stock OS file is and attached to the release first. No firmware
reaches the workflow.

## The macOS app

`packaging/build_macos.py --core core-2.1.elemod [...]` builds
`elekloader.app` the same way, universal2 (Apple silicon and Intel; it needs
a universal2 Python, such as python.org's). With `--identity` (a Developer
ID Application certificate in your keychain) every binary in it is signed
with the hardened runtime; without, it is signed ad hoc, for trying on
your own Mac. It runs the app's `--selftest` as it will ship, signed, then
writes `elekloader-<version>-macos.dmg` and `SHA256SUMS.txt`. `--notarize`
has Apple notarize the app and the `.dmg` and staples both, with an App Store
Connect API key in `NOTARY_KEY` (the `.p8` file), `NOTARY_KEY_ID` and
`NOTARY_ISSUER`.

The **macos-build** workflow (Actions, run by hand with a release's tag, like
windows-build) does all of that on GitHub's macOS runner and attaches the
`.dmg` to the release, adding its line to `SHA256SUMS.txt`. With **test**
ticked, it builds the branch it is run on with the given release's cores,
signs, notarizes and self-tests it the same way, and keeps the `.dmg` as the
run's artifact instead of attaching it: a check of the signing before a
release. It needs these repository secrets:

| secret | what |
|---|---|
| `MACOS_CERTIFICATE` | the Developer ID Application certificate with its private key, exported from Keychain Access as a `.p12`, base64-encoded |
| `MACOS_CERTIFICATE_PASSWORD` | the password the `.p12` was exported with |
| `NOTARY_KEY` | an App Store Connect API key's `AuthKey_<id>.p8`, its text as it is |
| `NOTARY_KEY_ID` | that key's ID |
| `NOTARY_ISSUER` | the Issuer ID shown above the keys in App Store Connect |
