# Contributing to pyxis-defs

This repo holds memory-structure definitions for applications, written in the [Pyxis DSL](https://github.com/ferrobrew/pyxis). Each project is a tree of `.pyxis` files plus a `pyxis.toml`; the generated JSON docs live under `docs/`.

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

Many engines prefix struct types (e.g. `SVector3`) and classes (e.g. `CGameObject`). Drop these prefixes in pyxis: `Vector3`, `GameObject`, `SharedPtr`. Keep the prefix only when stripping would collide with another type — rare, but use your judgement.

### Module structure mirrors the source application

One `.pyxis` file per module; folders nest. Use `use` to import cross-module types (same syntax as Rust: `use types::{math::Matrix4, rtti::Rtti};`). A folder that needs its own items gets a `mod.pyxis`.

### Backend-provided methods: prefer `#[external_body]`

When a type's method body is supplied by a backend prologue/epilogue rather than bound to a binary address, declare it as a backend-gated `#[external_body]` method so it shows up on the type's page:

```pyxis
#[cfg(backend = "rust")]
impl Widget {
    /// Rust-only helper; body lives in the cfg-gated `epilogue` below.
    #[external_body]
    pub fn spin(&self) -> u32;
}

#[cfg(backend = "rust")]
epilogue for Widget r#"
    impl Widget {
        pub fn spin(&self) -> u32 { self.value * 2 }
    }
"#;
```

`#[external_body]` is backend-agnostic: the Rust backend skips emission (the epilogue's own `impl` is the sole source, so the two never conflict), the C++ backend routes the declaration to the header, and the JSON/docs surface it as an associated function with `body: external` and the `cfg` attached. Gate the impl block with `#[cfg(backend = "...")]` so each backend only sees its own declarations.

When a method exists for more than one backend (e.g. `SharedPtr::exists`), declare it once per backend under its own `#[cfg(backend = "...")]` impl block. Pyxis treats cfg-disjoint declarations (different `backend = "..."` values) as distinct methods, so both surface on the type page. Declarations whose cfgs could both be active in one build (e.g. two ungated, or two `backend = "cpp"`) are still rejected as duplicates.

The function grammar only models plain inherent methods / associated functions — `&self`/`&mut self`/named args, return type, method type params. It can't express:

- trait impls (`impl Clone/Drop/Default/PartialEq for Foo`),
- `unsafe fn`,
- by-value `self`,
- `where`-clauses,
- free generic functions or `From`/`Into` conversions / extension traits.

For those, leave the body in the epilogue as opaque text and tag it `for <Type>` so it renders on the type's page rather than the module page:

```pyxis
#[cfg(backend = "rust")]
epilogue for Widget r#"
    impl Drop for Widget {
        fn drop(&mut self) { /* ... */ }
    }
"#;
```

### Attributes worth knowing

`#[size(..)]` / `#[align(..)]` on types; `#[address(0x..)]` on functions and extern values; `#[base]` on a region for composition-based inheritance; `#[index(n)]` on vftable entries; `#[cfg(backend = "..")]` to gate per backend; `#[cpp_name]` / `#[cpp_header]` / `#[rust_name]` on `extern type`s to bind the opaque extern to a concrete backend type. Doc comments (`///`) become the docs.

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

- Run `pyxis fmt` on changed files (`pyxis fmt --check` to verify) — the pretty-printer is canonical; CI also runs it.
- Run `python build.py --no-install` to confirm every project still builds.
- Run `python build.py --no-install --check-builds rust` before pushing; the generated Rust must compile against the Windows targets.
- Don't commit `docs/` by hand. CI (`.github/workflows/build-docs.yml`) regenerates and commits the `docs/` tree on push to `main` whenever `projects/**` or `build.py` changes; the checked-in `docs/` is what the viewer consumes.
