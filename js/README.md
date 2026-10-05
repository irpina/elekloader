# elekloader in TypeScript

elekloader's mod manager as a TypeScript package with no dependencies, for web pages and workers. It covers:
- Elektron OS files: the Digitakt mk1 and II, the Digitone mk1 and the Octatrack;
- the `.elemod` checks and the linker;
- the build with its verification;
- the web page's bridge.

The Python package in this repository is the reference. For the same stock file and mods, this engine writes the same files byte for byte (the `.syx`, the `.bin`, the manifest, the symbol map). It refuses the same things with the same messages and says the same about each mod. `tools/parity.ts` checks all of that against the Python.

It exists so a page can build firmware without Pyodide. That was a 9 to 13 MB download and a second or two of start-up before the first build; this is about 165 KB of JavaScript. It is also much faster: the packer runs in milliseconds, not seconds.

Licence: GPL-3.0-or-later (LICENSE). It is ported from elekloader's Python (GPL-2.0-or-later, used here under version 3). The ColdFire decoder comes from [modwerk](https://github.com/repeat98/modwerk) (GPL-3.0-or-later), which ported it from the same Python.

## Use

```ts
import { Bridge } from 'elekloader'          // src/index.ts; or dist/index.js after `node tools/build.ts`

const engine = new Bridge()
engine.addCore({ name: 'core-2.1-os1.54.elemod', sha256 }, coreBytes)   // the cores your site carries
const stock = await engine.setStock({ name: 'Digitakt_OS1.54.syx' }, stockBytes)   // or Elektron's .zip
const added = engine.addMod({ name: 'digislicer-2.1-os1.54.elemod' }, modBytes)
const enabled = engine.tick({ enabled: [], path: added.mod.path })   // the mod and what it requires
const check = engine.check({ enabled })                             // the live check: {ok, headline, problems, status}
const built = await engine.build({ enabled, version: '2.0a', name: 'custom.syx' })
// built.files: [{name, bytes, sha256, data}]: the .syx (and the Octatrack's .bin), the manifest, the symbol map
```

The calls are `web/bridge.py`'s: the same names and arguments, and the same results (`call(name, args, data)` takes the Python names). A page that ran the Python in Pyodide can switch without changing its interface. Below the bridge:
- `LoaderModel` is the desktop window's logic.
- `build()` and `save()` are the command line's.
- `link()`, `apply()`, `formats`, `syx` and `elek` are the layers under them.

Each `src/` file says which Python module it ports.

Nothing here touches the network or a device, and files stay in memory (`Store`).

## The kit, for websites

`src/kit/` puts the engine on any website ([docs/INTEGRATING.md](../docs/INTEGRATING.md)):
- **`worker.ts`:** a builder worker that keeps to the site it is served from;
- **`client.ts`:** `createBuilder`, the page's promise API;
- **`catalog.ts`:** the catalog format (the cores and mods a site offers, pinned by sha256), and planning a selection;
- **`build.ts`:** the build page's helpers: prepare, the three build steps, the build log as text.

`tools/kit.ts` copies a catalog's files (`sync`), checks them (`verify`), pins the kit and the catalog (`lock`), and builds elekloader's curated catalog (`feed`). `examples/minimal/` is the smallest site. Each release attaches the kit as `elekloader-kit-<version>.zip` (`packaging/build_kit.py`) and the catalog as `elekloader-catalog.json`.

## Test

```bash
node --test "test/*.test.ts"     # no firmware needed: Node 22.18 or newer runs the TypeScript directly
```

The unit tests compare against what Python gave for synthetic inputs (`test/vectors.json`, written by `tools/vectors.py`). That covers:
- the packer, the depacker, both transports and the card file;
- SHA-256 and HMAC;
- `json.loads` and its messages, `int(x, 0)`, `repr()`, `json.dumps`;
- the zip reader.

With your own stock files and mods (which never go in the repository), compare everything against the Python:

```bash
node tools/parity.ts plan config.json cases.json      # cases from your files, and broken copies of a mod
python3 tools/parity.py cases.json py.json            # the Python's results (a POSIX system: WSL on Windows)
node tools/parity.ts compare cases.json py.json       # this engine's, compared

node tools/bridge_parity.ts plan config.json sessions.json   # a page's calls, in sessions
python3 tools/bridge_parity.py sessions.json py.json         # through web/bridge.py (it needs /work)
node tools/bridge_parity.ts compare sessions.json py.json    # every reply compared

python3 tools/isa_parity.py <stock file> isa.bin      # the decoder, at every even offset of the main OS
node tools/isa_parity.ts <stock file> isa.bin

node tools/smoke.ts <stock file> <mod>...             # one build through the bridge, timed
```

`tools/parity.ts` documents the config.

## Python behaviour it keeps

Some details look odd in TypeScript. They are what the Python does, kept on purpose:
- **JSON** is read with Python's rules (`pyjson.ts`). NaN and Infinity are accepted, a float such as `4.0` stays a float (refused where an integer is wanted), and an error says what Python's says, with line, column and character.
- **Numbers** in a mod may be strings Python's `int(x, 0)` reads: `"0x10"` and `"1_000"` are accepted, `"010"` is not.
- **A malformed mod that crashes the Python crashes here too**, with the Python exception's name (`py.ts`): iterating a null, or `.get` on a list. It is never accepted.
- **Manifests are written as Python's `json.dumps` writes them** (`py.dumps`): key order kept, non-ASCII escaped. A Map keeps keys such as section ids in their order.
- **Hashes are synchronous** (`bytes.ts`): a page, a worker and Node run the same code. Web Crypto's digest is asynchronous.
