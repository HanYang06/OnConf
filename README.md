<!--
  TODO(rename): 项目名与仓库地址尚未定案。定案后需全局替换的字符串：
    auto-conf / auto_conf / HanYang06/auto-conf / hanyang06.github.io/auto-conf
  替换点：README.md、README.zh-CN.md、pyproject.toml、mkdocs.yml、CONTRIBUTING.md、
          SECURITY.md、SUPPORT.md、docs/**、.github/**、NOTICE、CODE_OF_CONDUCT.md。
-->

# auto-conf

[![CI](https://github.com/HanYang06/auto-conf/actions/workflows/ci.yml/badge.svg)](https://github.com/HanYang06/auto-conf/actions/workflows/ci.yml)
[![CodeQL](https://github.com/HanYang06/auto-conf/actions/workflows/codeql.yml/badge.svg)](https://github.com/HanYang06/auto-conf/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/HanYang06/auto-conf/badge)](https://securityscorecards.dev/viewer/?uri=github.com/HanYang06/auto-conf)
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

> [!WARNING]
> **Pre-Alpha (`0.1.0`) — evaluate only, do not deploy.**
> The API and the on-disk format can change without a deprecation period.
> **The closing clause of the line above is the M3 acceptance criterion, not a delivered fact.**
> The byte half — *without losing a byte* — is implemented and tested (surgical write-back).
> The update half is **not**: there is no file locking yet and writes are not atomic, so a crash
> or a concurrent writer can still lose an update or truncate a file.
> See [Known limitations](#known-limitations) and the
> [threat model](docs/security/threat-model.md) before you rely on this.

Chinese documentation (design draft and threat model included) lives at
<https://hanyang06.github.io/auto-conf/>.

---

## What it is

A configuration engine for programs that keep their settings in **plain files they can read and edit by hand**.

- **Declared in code, owned by the files.** You declare keys and their types in Python;
  the files on disk remain the single source of truth. Code is not authoritative.
- **Surgical write-back.** When the engine changes one key, every byte it did not need to
  touch stays exactly where it was — comments, indentation, key order, blank lines.
- **One flat key space, many backends.** `app.server.port` addresses the same logical key
  whether it lives in JSON, YAML, TOML or a `.env` file.
- **A vocabulary next to your values.** The engine maintains a JSON Schema describing
  which keys exist, so your editor can autocomplete and validate the config file.
- **No server, no daemon, no network.** It is a library that runs in your process.

## What it is not

- **Not a config server / settings center.** There is no service to run.
- **Not a secrets manager.** Values live in plain files.
- **Not distributed.** Cross-machine consistency is your release system's job, not this library's.
- **Not `pydantic-settings`.** It does not validate your env vars into a typed object graph;
  it keeps your files authoritative and writes back into them.

## Quick start

`auto-conf` is **not on PyPI yet** (the distribution name is still being decided).
Install from source:

```bash
git clone https://github.com/HanYang06/auto-conf.git
cd auto-conf
uv sync --all-groups
```

Then, from a scratch directory:

```python
from auto_conf import AutoConf, conf

AutoConf(home="./conf")        # optional — omit it and the engine follows its conventions
conf("app.server.port", 8080)  # declare + write; returns the now-effective value
print(conf("app.server.port")) # read
```

This is the actual, verified output of that snippet:

```console
$ uv run python -c "from auto_conf import conf; print(conf('app.server.port', 8080)); print(conf('app.server.port'))"
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
  "x-auto-conf-hash": "5778fdddf8dfa9be"
}
```

## The two faces

Everything goes through two callables. That is the whole public surface.

| Face | Purpose |
|---|---|
| `AutoConf(**engine)` | Configure **the engine itself**: `home` (config directory) and `audit`. Optional — the conventions work without it. |
| `conf(key, value=..., *, doc=..., type=..., force=..., **engine)` | Do all the work: read, write, register. |

`conf` infers the operation from the **shape of the call**, not from an `op` argument:

```python
conf("app.port")                    # read; raises if the key has no value
conf("app.port", 9090)              # declare + write; returns the effective value
conf("app.port", doc="服务端口")     # register a key without a value (required key)
conf("app.port", 9090, force=True)  # overwrite a value already present in the file
```

Notes on semantics that surprise people:

- `type=` performs a **declaration-time consistency check only**. The engine is transparent
  about values and never converts them on read. Want an `int` out of a `.env` file?
  Write `int(conf("PORT"))` — explicit, and visible at the call site.
- Reading a key that was never declared raises `KeyNotRegisteredError`; a declared key with no
  value raises `KeyHasNoValueError`; a value contradicting its declared type raises
  `TypeConflictError`.
- The commit point is **immediate** (`atexit` triggers a final `sync()`), not a batching window.
- The engine is a singleton: once started, it cannot be reconfigured in place.

## Currently implemented

| Area | Status |
|---|---|
| JSON value backend — surgical write-back | ✅ |
| YAML value backend — comments, anchors, key order preserved | ✅ |
| `.env` value backend — string-only, no inline comments, no key renaming | ✅ |
| TOML value backend — table headers normalized to dotted keys | ✅ |
| Vocabulary (key space) — persisted, JSON Schema round-trip, hash short-circuit | ✅ |
| Engine assembly — `conf` / `AutoConf` end-to-end | ✅ |
| Value-as-key (indirect addressing) + guaranteed `$schema` pointer on every write | ✅ |
| Error taxonomy — `ConfError`, `KeyNotRegisteredError`, `KeyHasNoValueError`, `TypeConflictError`, `UnknownEngineParamError`, `EnvSyntaxError` | ✅ |
| Test suite — one file per module plus security invariants | ✅ green locally; CI runs it on ubuntu / windows / macos |

## Roadmap — not available yet

Do not plan around these; they are **not implemented**:

| Capability | Milestone |
|---|---|
| File locking + WAL + prefix-sharded locks (actually-safe cross-process writes) | M3 |
| Atomic write (temp file + rename) and `fsync` | M3 |
| Restrictive file permissions for newly created config files | M3 |
| Transaction batching / write coalescing | M3 |
| Audit report and audit event stream (`audit=` is accepted but inert) | M4 |
| System environment variables as a configuration **source** (`AUTO_CONF_HOME` only locates the config dir) | — |
| Per-format vocabulary export | — |
| IPC (TCP loopback + HTTP) and the subprocess writer model | — |
| A real CLI (`auto-conf` currently prints the config directory and exits) | — |

See [`docs/roadmap.md`](docs/roadmap.md) for the full breakdown and
[`docs/design/DESIGN.md`](docs/design/DESIGN.md) for the design draft (Chinese, still under review).

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

CI runs on **ubuntu / windows / macos × Python 3.14** and enforces: `ruff check`, `mypy --strict`,
`pytest` with a coverage floor, `bandit`, `pip-audit`, `zizmor`, `actionlint`, `gitleaks`,
CodeQL, dependency review and OpenSSF Scorecard.

`ruff format --check` is currently **non-blocking** (`continue-on-error` in CI): the team decided
not to reflow the existing files while the library is still being written.

## Security

Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md). Do not open a public issue.

Invariants this project commits to (each one has a regression test in
[`tests/test_security_invariants.py`](tests/test_security_invariants.py)):

- the default path opens **no network ports** and spawns **no subprocesses**
- configuration is only ever parsed with `yaml.safe_load` — never `yaml.load`
- key names never become filesystem paths
- no `eval` / `exec` / `pickle` on configuration content

### Known limitations

| Limitation | Consequence |
|---|---|
| **No file locking** | Concurrent writers to the same value file can lose updates or interleave content |
| **Writes are not atomic** | A crash mid-write can leave a truncated config file (`write_text`, no temp+rename, no `fsync`) |
| **File permissions are not set** | New files follow the system umask; on umask 022 a `.env` holding secrets may be readable by other users |
| **Symlinks are followed** | If a value file is a symlink, the write lands on its target |
| **`AUTO_CONF_HOME` is trusted input** | It decides the config directory and is not containment-checked |

Full analysis, per threat with code evidence: [`docs/security/threat-model.md`](docs/security/threat-model.md).

## Project layout

```text
src/auto_conf/
  __init__.py        # the two faces: AutoConf + conf
  _engine.py         # engine assembly, directory conventions, write-back
  _core.py           # reconciliation: the three-set algorithm
  _vocab.py          # vocabulary + JSON Schema
  _textscan.py       # shared byte-level scanning used by the backends
  _json_backend.py   # JSON value backend
  _yaml_backend.py   # YAML value backend
  _env_backend.py    # .env value backend
  _toml_backend.py   # TOML value backend
  errors.py          # error taxonomy
tests/               # one file per module + security invariants
docs/                # documentation site sources (Chinese)
  design/DESIGN.md   # the design draft — authoritative for *intent*, not for *status*
```

The module list grows as backends land; `src/auto_conf/` itself is authoritative.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first. Commits follow
[Conventional Commits](https://www.conventionalcommits.org/) and may use a Chinese subject.
By participating you agree to the [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## License

[Apache-2.0](LICENSE) © 2026 HanYang06. Third-party components are listed in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
