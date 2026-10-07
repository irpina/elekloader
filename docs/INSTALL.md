[elekloader docs](README.md) › Install

# Install

There are three ways to run elekloader, and they build the same files. Each
needs the stock OS file for your device ([below](#the-stock-os-file)).

## In your browser

Nothing to install: <https://irpina.github.io/elekloader/>.
Drop in your stock OS file, add mods from its library or your own, tick them,
build, and download the `.syx` (and, for the Octatrack, the `.bin`). The build runs in the page, in
Python compiled to WebAssembly ([Pyodide](https://pyodide.org)), with
elekloader's own code, unchanged. The page shows its version and commit, and
whether that is the latest release's. Your files are never uploaded, the
site hosts no firmware, and it fetches nothing from any other site. The
core for your device is listed and ticked for you. See
[WEB.md](WEB.md).

## Windows

Download `elekloader-<version>-windows.exe` from
[Releases](https://github.com/irpina/elekloader/releases/latest) and run it.
There is nothing to install and no Python needed. The first time, it asks
for your stock OS file. The **core** mod is built in: it is listed in the window, and ticked for you
with any mod that needs it. The exe is not signed, so Windows may say it
protected your PC: choose **More info**, then **Run anyway**.

## macOS

Download `elekloader-<version>-macos.dmg` from
[Releases](https://github.com/irpina/elekloader/releases/latest), open it,
and drag **elekloader** to **Applications**. It runs on Apple silicon and
Intel Macs, with no Python needed, and it is signed and notarized by Apple.
As on Windows, the first time it asks for your stock OS file, and core is
built in.

## From source, on any system

Python 3.9 or newer, nothing else to install
(on Linux, Tkinter may be a separate package, such as `python3-tk`).
Download or clone this repository, then `python -m elekloader` opens the
window. With `pip install .` the commands are `elekloader` (the window) and
`elekpatch` (the command line: [BUILDING.md](BUILDING.md#on-the-command-line)).

From source, core is not built in. Take your device's from
[Releases](https://github.com/irpina/elekloader/releases/latest) (or build
it), and install it like any mod. [CORES.md](CORES.md#which-file) lists the
file for each device and OS.

## The stock OS file

You need the stock OS file for your device, exactly as Elektron
publishes it:
- Digitakt mk1: `Digitakt_OS1.54.syx` or `Digitakt_OS1.53.syx`, from
  [Elektron's Digitakt downloads](https://www.elektron.se/support-downloads/digitakt);
- Digitakt II: `Digitakt_II_OS1.17.syx`, from
  [Elektron's Digitakt II downloads](https://www.elektron.se/support-downloads/digitakt-ii);
- Digitone mk1 or Digitone Keys: `Digitone_and_Digitone_Keys_OS1.44.syx` or
  `..._OS1.43.syx` (one file serves both), from Elektron's Digitone downloads;
- Octatrack MKI or MKII: `OCTATRACK_OS1.40C.syx` or `OCTATRACK_OS1.40C.bin`
  (one file serves both), from Elektron's Octatrack downloads.

The `.zip` Elektron's site gives you works as it is. elekloader recognises
the file by its hash.

A mod is made for one OS version: one built for 1.53 is refused with a 1.54
stock file, and its author has to build it for 1.54 ([ADAPTING.md](ADAPTING.md),
3.10 "Another OS version").

Next: [build, flash and recover](BUILDING.md).
