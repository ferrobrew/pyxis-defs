# Contributing to pyxis-defs

This repo holds memory-structure definitions for applications, written in the [Pyxis DSL](https://github.com/ferrobrew/pyxis). Each project is a tree of `.pyxis` files plus a `pyxis.toml`; the generated JSON docs live under `docs/`.

For the Pyxis language reference (syntax, types, attributes, cfg, splices), see [docs/language.md](https://github.com/ferrobrew/pyxis/blob/main/docs/language.md). For backend-specific docs, see the [docs directory](https://github.com/ferrobrew/pyxis/tree/main/docs). This file covers only conventions specific to this repo.

## Layout

```
projects/<App>/<Store>/<version-id>/
    pyxis.toml      # [project] name = "..." ; pointer_size = 4 | 8
    *.pyxis          # one module per file; folders nest modules
    <dir>/mod.pyxis  # a folder's own module (mirrors Rust's mod.rs)
```

`pointer_size` selects the ABI the defs target. The build/check harness compiles generated Rust against the matching `i686-`/`x86_64-pc-windows-msvc` target, so the layout assumptions (memory offsets, vtable indices) are verified, not just parsed.

## Conventions

### Strip engine-specific type prefixes

Many engines prefix struct types (e.g. `SVector3`) and classes (e.g. `CGameObject`). Drop these prefixes in pyxis: `Vector3`, `GameObject`, `SharedPtr`. Keep the prefix only when stripping would collide with another type - rare, but use your judgement.

### Module structure mirrors the source application

One `.pyxis` file per module; folders nest. Use `use` to import cross-module types (same syntax as Rust: `use types::{math::Matrix4, rtti::Rtti};`). A folder that needs its own items gets a `mod.pyxis`.

### `#[external_body]` and backend-specific code

When a type's method body is supplied by a backend prologue/epilogue rather than bound to a binary address, declare it as a backend-gated `#[external_body]` method. The full syntax and semantics are in the [language reference](https://github.com/ferrobrew/pyxis/blob/main/docs/language.md#backend-splices); the key convention for this repo is:

- Declare `#[external_body]` methods under `#[cfg(backend = "...")]` impl blocks so each backend only sees its own declarations.
- When a method exists for more than one backend, declare it once per backend under its own cfg-gated impl block.
- For things the function grammar can't express (trait impls, `unsafe fn`, by-value `self`, `where`-clauses, extension traits), put the body in a `for <Type>` epilogue so it renders on the type's page.

### Cross-backend analogs in doc comments

When a method exists in one backend but has an analog in another, document the relationship in a doc comment so readers understand the mapping without cross-referencing epilogues.

### `unknown<N>` for untyped regions

Use `unknown<N>` for padding, reserved fields, or data whose layout hasn't been mapped yet rather than inventing a fake type.

## Building and verifying

`build.py` is the entry point. It expects `pyxis` on `PATH` (see [pyxis](https://github.com/ferrobrew/pyxis)).

```sh
# Generate JSON docs for every project into docs/ and refresh docs/index.json.
# Installs pyxis from git main by default.
python build.py

# Use the pyxis already on PATH (e.g. a locally installed one):
python build.py --no-install

# Install a specific pyxis source:
python build.py --branch <branch>
python build.py --tag <tag>
python build.py --rev <commit>
python build.py --path /path/to/pyxis        # local checkout

# Generate a different backend (json -> docs/, else -> <backend>/):
python build.py --backend rust
```

### Compile-checking generated output

The defs reference dependencies (the `windows` crate, `glam`, `bevy_math`) the consumer provides, so a parse/semantic pass alone isn't enough. `--check-builds` generates each project's output into a throwaway crate and compiles it against the matching Windows target:

```sh
# One-time: install the Windows targets the harness builds against.
rustup target add i686-pc-windows-msvc x86_64-pc-windows-msvc

# Compile-check generated Rust for every project (32- and 64-bit).
python build.py --no-install --check-builds rust

# Also check C++ output (needs an MSVC or clang-cl + xwin toolchain):
python build.py --no-install --check-builds rust,cpp
```

Per-project dependency overrides live in `RUST_CHECK_OVERRIDES` in `build.py`; add an entry there when a new project pulls in a dependency the check crate doesn't already supply.

The C++ check needs a toolchain: native MSVC on Windows, or `clang-cl` + `xwin` on Linux pointed at via `PYXIS_CHECK_CMAKE_TOOLCHAIN_X86` / `_X64` (see pyxis's `CONTRIBUTING.md`). It's skipped (not failed) when no toolchain is configured for a project's architecture.

## When changing defs

- Run `pyxis fmt` on changed files (`pyxis fmt --check` to verify) - the pretty-printer is canonical; CI also runs it.
- Run `python build.py --no-install` to confirm every project still builds.
- Run `python build.py --no-install --check-builds rust` before pushing; the generated Rust must compile against the Windows targets.
- Don't commit `docs/` by hand. CI (`.github/workflows/build-docs.yml`) regenerates and commits the `docs/` tree on push to `main` whenever `projects/**` or `build.py` changes; the checked-in `docs/` is what the viewer consumes.
