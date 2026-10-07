# OnConf

[![CI](https://github.com/HanYang06/OnConf/actions/workflows/ci.yml/badge.svg)](https://github.com/HanYang06/OnConf/actions/workflows/ci.yml)
[![CodeQL](https://github.com/HanYang06/OnConf/actions/workflows/codeql.yml/badge.svg)](https://github.com/HanYang06/OnConf/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/HanYang06/OnConf/badge)](https://securityscorecards.dev/viewer/?uri=github.com/HanYang06/OnConf)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/downloads/)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue.svg)](pyproject.toml)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](.pre-commit-config.yaml)

**English** · [简体中文](README.zh-CN.md)

> **Configuration has no verbs: one name reads and writes it, in both directions, without losing a byte or an update.**
>
> **配置不再有动词：同一个名字读它、写它，两个方向都不丢——不丢一个字节，也不丢一次更新。**

The two lines above are the **official positioning statement**; English and Chinese are one pair, so
changing one requires changing the other — plus `README.zh-CN.md`, `pyproject.toml`'s `description`,
`mkdocs.yml`'s `site_description` and `docs/index.md`.

> [!IMPORTANT]
> **`1.0.0` — the first stable release** (2026-10-04). The public API and the on-disk format now
> follow [semantic versioning](https://semver.org/): from here on they change only in a **major**
> release, and every change is recorded in the [changelog](CHANGELOG.md).
> **Both `1.0` and `2.0` are breaking-change releases**: **follow 2.0 from here on**;
> the 1.0 shape lives in [the 1.0.x roadmap](docs/roadmap/1.0.x/roadmap.md).
> **Both halves of the line above have mechanism behind them**: *without losing a byte* by
> surgical write-back, and *without losing an update* by a **dedicated writer** — whichever process
> first claims a config directory serves every other process over a local named pipe (Windows) or
> Unix socket (POSIX), with a cross-process **OS** lock plus a re-read under that lock as the
> fallback.
> Writes are atomic too: same-directory temp file → `fsync` → `os.replace` (plus a parent-directory
> `fsync` on POSIX), preserving the file's original line endings and permissions.
> Read [Known limitations](#known-limitations) and the
> [threat model](docs/security/threat-model.md) before you rely on this.

Chinese documentation (design draft and threat model included) lives at
<https://hanyang06.github.io/OnConf/>.

---

## What it is

A configuration engine for programs that keep their settings in **plain files they can read and edit by hand**.

- **Declared in code, owned by the files.** You declare keys (and optionally a description)
  in Python; the files on disk remain the single source of truth. Code is not authoritative,
  and the runtime never overwrites a value the file already has.
- **Surgical write-back.** When the engine changes one key, every byte it did not need to
  touch stays exactly where it was — comments, indentation, key order, blank lines.
- **One flat key space, JSON first.** `app.server.port` addresses the same logical key
  whether it lives in JSON, YAML, TOML or a `.env` file. **JSON is the primary value format**
  — it is the default `file_type`, the most capable one, and the one the `$schema` pointer
  (editor completion) is built around; YAML / TOML / `.env` are **optional backends**, not
  peers of the default.
- **A vocabulary next to your values.** The engine maintains a JSON Schema describing
  which keys exist, so your editor can autocomplete and validate the config file.
- **No separate process, no daemon, no network.** It is a library that runs in *your* process. The
  one piece of machinery is a **writer thread** inside whichever process first claims the config
  directory; it serves the others over a local pipe, authenticated with a key under `schema/`. No
  ports are opened and no child process is spawned.

## What it is not

- **Not a config server / settings center.** There is no service to run.
- **Not a secrets manager.** Values live in plain files.
- **Not distributed.** Cross-machine consistency is your release system's job, not this library's.
- **Not `pydantic-settings`.** It does not validate your env vars into a typed object graph;
  it keeps your files authoritative and writes back into them.

## Quick start

`onconf` is on PyPI as [`OnConf`](https://pypi.org/project/OnConf/):

```bash
uv add onconf
```

Or install from source:

```bash
git clone https://github.com/HanYang06/OnConf.git
cd onconf
uv sync --all-groups
```

Then, from a scratch directory:

```python
from onconf import AutoConf, conf

AutoConf(home="./conf")  # optional — omit it and the engine follows its conventions
conf("app.server.port", 8080)  # declare + write; returns the now-effective value
print(conf("app.server.port"))  # read
```

This is the actual, verified output of that snippet:

```console
$ uv run python -c "from onconf import conf; print(conf('app.server.port', 8080)); print(conf('app.server.port'))"
8080
8080
```

It creates two files:

```jsonc
// ./conf/settings.json — yours to edit by hand
{
  "$schema": "schema/settings.json",
  "app.server.port": 8080
}
```

```jsonc
// ./conf/schema/settings.json — the engine's own asset, regenerated as needed
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "app.server.port": { "default": 8080 }
  },
  "x-onconf-hash": "5778fdddf8dfa9be"
}
```

## The two faces

Everything goes through two callables. That is the whole public surface.

| Face | Purpose |
|---|---|
| `AutoConf(**engine)` | Configure **the engine itself**: `home` (config directory, default `./conf`), `file_name` (value-file name stem, default `settings`), `file_type` (which value file to use — single-valued, default `"json"`), `no_one_file` (multi-file: a key's `<path>:` prefix addresses `<home>/<path>.<ext>`), `log_path` (where the audit file goes — empty means `<home>/audit.log`, and a relative path resolves against `<home>`), `log_console` (whether the human-readable copy also goes to `stderr`; default `True`), `log_rotate` / `log_scrub` / `log_encode` (three optional hooks: which file the next batch goes to, redaction of a record before it lands, and the final bytes on disk), `identity` (optional `service@host` tag recorded on each line) and `flush_window` (batching window; `0` = commit immediately). Optional — the conventions work without it. |
| `conf(key, value=..., doc=...)` | Do all the work: read, write, register. |

Value-file *names* (and the embedded paths of multi-file keys) are the only external strings
that ever reach the filesystem, so they go through one containment check: a plain file name,
no separators, no `..`, never absolute, and the resolved path must stay inside `<home>`.

`conf` picks its mode from the **shape of the call** — nothing else. The rule is simply
*"is the `value` slot filled in?"*:

```python
conf("app.port")                    # read; raises if the key has no value
conf("app.port", 9090)              # declare + write; returns the effective value
conf("app.port", 9090, "服务端口")   # same, plus a description registered in the vocabulary
conf("app.port", doc="服务端口")     # register a key without a value (required key)
```

Hard rules:

- **`None` / `""` / `0` all count as filled in**; `MISSING` is the only sentinel.
- The second position always belongs to `value`, so `conf(key, x)` is *always* a write;
  the "register only" mode can only be triggered by the `doc=` keyword.
- `doc` is a **positional** third parameter and the only registration metadata there is.
  The rule is just that one bit, so the parameter surface is **closed**: adding a parameter
  later does not touch it.
- The usage face **cannot configure the engine**: `conf(..., home=…)` is a `TypeError`.

Notes on semantics that surprise people:

- **There is no type declaration any more, and the engine never converts values.** A `.env`
  file gives you `"8080"`, so write `int(conf("PORT"))` at the call site if you want an `int` —
  explicit, and visible where it happens.
- **The same key can come back with different types on different backends**, and that is
  deliberately **not portable**: `conf("app.tags")` is the list `["a", "b"]` on JSON and the
  string `"['a', 'b']"` on `.env`. The difference is not recorded in the vocabulary — it is
  written here instead, because "the carrier can express it" is the whole rule.
- Reading a key that was never declared raises `KeyNotRegisteredError`; a declared key with no
  value raises `KeyHasNoValueError`.
- **The runtime never overwrites a value that is already in the file.** If the file says `8080`
  and your code declares `9090`, the file is left byte-for-byte alone and an `op=skip` record is
  logged — the call still returns the effective value `8080`. Overwriting is a human decision:
  `onconf sync` will not touch an existing value either, and `onconf build` rebuilds the file
  from the declarations instead.
- Only two things are ever written at runtime: **keys that are missing** and **vocabulary
  metadata**.
- The engine config has two layers: the **bootstrap layer** (`home`, `file_name`, `file_type`,
  `no_one_file`, `log_path`, `log_console`, `log_rotate`, `log_scrub`, `log_encode`, `identity`,
  `flush_window`) cannot be changed once the engine is running — that would amount to editing
  your code; the **value layer** may change at any time, because values are re-read from the file.
- **Who may write** is decided by the process tree, not by a flag: the process that created the
  engine instance is the **owner** (read + write + regenerate the vocabulary); a process derived
  from it — `fork`, or `spawn`/`subprocess` that inherited `ONCONF_OWNER_PID` — is **read-only**
  and gets a `ConfError` the moment it tries to write. Inside one process, several instances and
  several threads on the same value file share one in-memory lock, so they never lose each
  other's keys.
- The commit point is **immediate by default** (`atexit` triggers a final `sync()`). A batching
  window is opt-in via `flush_window`; with it on, disk is touched at four commit points —
  window expiry, a read, `sync()`, and process exit.

## How to declare: **literals at the declaration site**

The calls that carry a `value` *are* the specification, so spell the key, the value and the
description as literals:

```python
conf("app.post", 8080, "server port")                  # yes
conf("slot.max.byte.b", 512, "one of the two tiers")   # yes
```

```python
APP_POST = "app.post"
conf(APP_POST, 8080)                 # no — legal Python, but the declaration is not a literal
for key, default in TIERS:
    conf(key, default)               # no — same thing, one indirection further
conf(build_key(), 8080)              # no
```

Reads are **not** restricted: `conf("app.post")` and `conf(APP_POST)` are both fine — a read
creates no persistent state, and a wrong constant fails loudly right there with
`KeyNotRegisteredError`.

**This is a convention, not an enforced rule** — it is legal Python but a bad fit here, and the
library will not police your code. What a hidden declaration costs you:

- **The CLI cannot see it.** `onconf build` / `onconf sync` find declarations by reading
  `conf(...)` arguments, so `sync` treats the key as *not declared*; while such calls exist it
  **refuses to delete anything** rather than guess (use `--no-clean` to keep going).
- **Static review loses it.** `grep app.post` does not find the declaration, and no tool that
  reads the call site can — including the `check` command we plan to add (which will emit a
  warning, never an error).
- **The site stops explaining itself.** Computed values and descriptions (`X if cond else Y`,
  f-strings) are invisible where you look; the loop/dict forms go further and leave "which keys
  do we even have?" unanswerable from the code.

Editor completion inside the value file is unaffected — the vocabulary is built at runtime from
whatever key was registered.

## Currently implemented

| Area | Status |
|---|---|
| **JSON value backend — the primary format** (default `file_type`) — surgical write-back | ✅ |
| YAML value backend — **optional**; comments, anchors, key order preserved | ✅ |
| `.env` value backend — **optional**; string-only, no inline comments, no key renaming | ✅ |
| TOML value backend — **optional**; table headers normalized to dotted keys | ✅ |
| Vocabulary (key space) — persisted, JSON Schema round-trip, hash short-circuit. It records exactly three things per key: the key, the description, the default | ✅ |
| Value-file selection — `file_name` (default `settings`) plus `file_type` (single-valued, default `"json"`) pick `<home>/<file_name>.<ext>` | ✅ |
| **Multi-file** — `no_one_file=True` makes a key's `<path>:` prefix address `<home>/<path>.<ext>` (e.g. `conf("app/conf/net:net.id.post", 8080)` → `<home>/app/conf/net.json`). Keys without a prefix still land in the default file. One vocabulary per `(home, file_name)`; every embedded path goes through the containment check | ✅ |
| Engine assembly — `conf` / `AutoConf` end-to-end | ✅ |
| **Process-tree write rights** — the process that creates the engine instance is the **owner** (read + write + regenerate the vocabulary). A process derived from it is **read-only** and gets a `ConfError` on its first write: `fork` is caught by a pid check, `spawn` / `subprocess` by the inherited `ONCONF_OWNER_PID`. The CLI clears that marker — "want a change? use the command line" | ✅ |
| **In-process lock** — one in-memory lock per value file, shared by every engine instance and every thread in the process, so they never lose each other's keys. It never touches the filesystem | ✅ |
| Re-read on change — fingerprint (`mtime` + `size`) over **both** the values file and the vocabulary, checked before every read and every write, so an external edit (or an owner's commit) is never missed | ✅ |
| **Atomic write, with a bounded retry** — same-directory temp file → `fsync` → `os.replace`, plus a parent-directory `fsync` on POSIX; original line endings and permission bits preserved, new files land as `0600`. On Windows the replace is retried briefly, because a concurrent *reader* holds the file open and readers take no lock | ✅ |
| Optional batching window — `flush_window` (default `0`, i.e. commit immediately), **per engine** | ✅ |
| Value-as-key (indirect addressing) + guaranteed `$schema` pointer on every write (JSON / YAML only — `.env` and `.toml` cannot hold a member, so the pointer is skipped) | ✅ |
| Error taxonomy — `ConfError` as the base, with `KeyNotRegisteredError`, `KeyHasNoValueError` and `UnknownEngineParamError`. `EnvSyntaxError`, `YamlFlatRequiredError` and `TomlFlatRequiredError` are `ValueError` subclasses, so they are **not** caught by `except ConfError` | ✅ |
| **Logging = audit** — one record stream, two sinks. The **file** sink is always on (`log_path`, default `<home>/audit.log`): append-only, `0600`, compact `key=value`, full dates, **never truncated**. The **console** sink (`stderr`) can be switched off (`log_console=False`) and, on a TTY, is coloured by `rich` — imported lazily in that branch only, so the mandatory path and pipes never pay for it and never see ANSI. Levels are `[Read]` / `[Write]` / `[Change]` / `[Error]` plus `[Start]`; writes are logged in full (including `op=skip` "wanted to change, respected the file" and `op=noop` "this batch's declaration was already satisfied"), reads are de-duplicated per transaction (`n=1000`); every write carries its call site (`at=app/config.py:12`), the pid and the optional `identity=`. Three optional hooks — `log_rotate` (which file the next batch goes to; **rotation changes the sink, it never renames a file**), `log_scrub` (redact a record before it lands) and `log_encode` (the final bytes on disk) — all default to *do nothing*. See the [log design](docs/design/log.md) | ✅ |
| **No runtime cleanup** — the runtime only fills what is missing and updates vocabulary metadata; it never deletes a key. Deletion lives in `onconf sync` (offline, one shot, over a complete declaration set) | ✅ |
| Test suite — one file per module plus security invariants | ✅ green locally; CI runs it on ubuntu / windows / macos |
| **CLI (seven commands)** — `onconf build` rebuilds the value file(s) and the vocabulary from the declarations (`--path` writes the whole rebuild into a new directory instead); `onconf sync` fills what is missing and deletes keys the declarations do not know (`--no-clean` keeps them). Declarations are found by **scanning the project for `conf(...)` calls** and reading their arguments — the single-function API is what makes that possible. Both commands support `--dry-run` (writes nothing) and `--json`; `sync` refuses to delete anything when some call could not be read statically. `onconf check` compares **three** things without writing a single byte — the declarations found in code, the vocabulary and the value files — and reports `missing` / `stale` / `default` / `doc` / `unfilled` / `undeclared`; `--verbose` adds the file each finding lives in, `--strict` counts warnings as failures. `onconf get` prints `key` / `value` / `path` / `doc` for every file that holds the key, `onconf set` changes the value of an existing key (or the vocabulary default, with `--default`), `onconf diff` lists the changes recorded in the audit log, and `onconf format --indent N` re-indents JSON value files | ✅ `build` / `sync` / `check` / `get` / `set` / `diff` / `format`; `add` / `log` are not implemented |

## Roadmap — not available yet

Do not plan around these; they are **not implemented**:

| Capability | Milestone |
|---|---|
| WAL (write-ahead log) — judged **unnecessary**: declarations are re-derivable from code, and the runtime only ever fills missing keys, so there is nothing to replay | not planned |
| C accelerator (future) — an **extra**, not a separate distribution: `pip install onconf[c]` | — |
| System environment variables as a configuration **source** (`ONCONF_HOME` only locates the config dir) | — |
| Per-format vocabulary export | — |
| `.env` `dict` / `list` values — behind the `env_file_dict` / `env_file_list` booleans (both default off); scalars stay strings | 2.2 (planned) |
| The other two CLI commands — `add` / `log` | 2.1 |
| `read` (file-level raw read) — deferred: it is only needed if the log can land as binary (`log_encode`); otherwise there is no raw byte to read back | — |
| `.pyproject.toml` / `.gitignore`-aware scan scope for the CLI (today it walks the project with a fixed skip list) | — |

See the [roadmap](docs/roadmap/README.md) for the full breakdown — it is the **single source of
truth for scope and versions** (numbered entries, decision state, version assignment);
[1.0.x](docs/roadmap/1.0.x/roadmap.md) is the frozen record of what shipped. The design docs
live under
[`docs/design/`](docs/design/index.md) (Chinese): [`init_config.md`](docs/design/init_config.md),
[`file_support.md`](docs/design/file_support.md), [`concurrency.md`](docs/design/concurrency.md),
[`log.md`](docs/design/log.md) and [`cli.md`](docs/design/cli.md).

## Quality gates

```bash
uv run pre-commit install --install-hooks   # one-time
uv run ruff check .
uv run mypy                                  # strict
uv run pytest
uv run pytest --cov --cov-report=term-missing
uv run bandit -c pyproject.toml -r src
uv run pip-audit
uv run zizmor .github/workflows
```

CI runs on **ubuntu / windows / macos × Python 3.14** and enforces: `ruff check`, `codespell`, the
third-party notices check (`python scripts/gen_third_party_notices.py --check`), `mypy --strict`,
`pytest` with a coverage floor, `bandit`, `pip-audit`, `zizmor`, `actionlint`, `gitleaks`,
CodeQL, dependency review and OpenSSF Scorecard.

`ruff format --check` is currently **non-blocking** (`continue-on-error` in CI): the team decided
not to reflow the existing files while the library is still being written.

## Security

Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md). Do not open a public issue.

Invariants this project commits to (each one has a regression test in
[`tests/test_security_invariants.py`](tests/test_security_invariants.py)):

- the default path opens **no network ports** and spawns **no subprocesses**
- YAML configuration is only ever parsed with `yaml.safe_load` / `yaml.safe_load_all` — never `yaml.load` (JSON uses `json.loads`, TOML `tomllib.loads`, `.env` a plain line scan)
- **external strings (the value-file name and the embedded paths of multi-file keys) reach the
  filesystem through one containment check only** — a plain name or relative path, no separators,
  no `..`, never absolute, resolved inside `<home>` (`src/onconf/_paths.py`)
- the CLI **never executes project code**: it parses `*.py` with `ast` and reads `conf(...)`
  call arguments — no `import`, no `eval`
- no `eval` / `exec` / `pickle` on configuration content
- the audit file (the file sink) is append-only (`O_APPEND`) and created `0600`, and its parent directory is never created by the log; the console sink can be switched off, the file sink cannot

### Known limitations

| Limitation | Consequence |
|---|---|
| **One writer per config directory is a deployment duty** | The engine takes no cross-process lock and does no coordination. Two peer processes that both write can lose each other's keys — prepare the config with `onconf sync` before starting them, and keep the runtime read-only |
| **A symlinked value file is replaced** | Writes go through `os.replace`: the symlink is replaced by a regular file and the link's target is left untouched (the link itself is destroyed) |
| **`ONCONF_HOME` and `ONCONF_OWNER_PID` are trusted input** | The first decides the config directory, the second decides whether this process may write; neither is containment-checked |
| **Log lines contain values verbatim** | `data=` / `old=` / `new=` carry the real value, and the file sink is **always on** — so `<home>/audit.log` (append-only, `0600`) holds real values with no switch to flip. Redaction and encryption are **hooks you supply** (`log_scrub` / `log_encode`), not features the engine ships (threat-model T12) |
| **The audit file may be appended by several processes** | Every process logs its own operations, and `txn` numbers are per-process — so the file can hold two batches numbered alike. Each line carries its pid, which is what a reader uses to tell them apart |
| **Code cannot overwrite a value that already exists** | When the file holds a value different from the one your code declares, the runtime respects the file (it logs `op=skip`) and returns the file's value. Overwriting is a human decision: `onconf sync` still will not touch an existing value — it only fills what is missing and deletes undeclared keys, and `onconf build` rebuilds the value file from the declarations (back it up first, or use `--path`) |
| **The runtime never deletes a key** | Value files accumulate keys that are no longer declared; `onconf sync` is what removes them |

Full analysis, per threat with code evidence: [`docs/security/threat-model.md`](docs/security/threat-model.md).

## The command line

Two of the nine planned commands are implemented (`build`, `sync`). Both find your
declarations by **scanning the project for `conf(...)` calls** — the single-function API is
what makes that possible — and neither one imports your code:

```console
onconf build                # rebuild <home>/settings.json + the vocabulary from the declarations
onconf build --path ./out   # write the whole rebuild elsewhere; the original is untouched
onconf sync                 # fill what is missing, then delete keys the declarations do not know
onconf sync --no-clean      # fill only — delete nothing
```

`--home` / `--file-name` / `--file-type` / `--no-one-file` mirror the `AutoConf` parameters,
`--dry-run` writes nothing at all, and `--json` prints the same data in machine-readable form.
Calls whose arguments are not literals (a variable, a loop, an expression) cannot be read
statically: they are listed as problems, and `sync` then **refuses to delete anything**.

## Project layout

```text
src/onconf/
  __init__.py        # the two faces: AutoConf + conf
  _engine.py         # engine assembly, directory conventions, write-back, the owner gate
  _paths.py          # the one entry point from external strings to paths (containment check)
  _core.py           # reconciliation: fill / metadata, plus `undeclared` for the CLI
  _cli.py            # the `onconf` entry point: build / sync (declarations by AST scan)
  _vocab.py          # vocabulary + JSON Schema
  _textscan.py       # shared byte-level scanning used by the backends
  _log.py            # the log: one record stream, two sinks, three hooks
  _json_backend.py   # JSON value backend
  _yaml_backend.py   # YAML value backend
  _env_backend.py    # .env value backend
  _toml_backend.py   # TOML value backend
  errors.py          # error taxonomy
tests/               # one file per module + security invariants
docs/                # documentation site sources (Chinese)
  design/init_config.md    # the two faces, bootstrap vs value layer, the three modes
  design/file_support.md   # value-file selection, return types, backends, vocabulary
  design/concurrency.md    # who may write, what a read sees, what the engine will not do
  design/log.md            # one record stream, two sinks, three hooks
  design/cli.md            # the command matrix: semantics, exit codes, what writes bytes
```

The module list grows as backends land; `src/onconf/` itself is authoritative.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first. Commits follow
[Conventional Commits](https://www.conventionalcommits.org/) and may use a Chinese subject.
By participating you agree to the [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## License

[Apache-2.0](LICENSE) © 2026 HanYang06. Third-party components are listed in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
