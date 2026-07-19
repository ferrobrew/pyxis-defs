#!/usr/bin/env python3
"""
Build script that finds all pyxis.toml files and builds them with pyxis.
For the JSON backend, generates an index.json file with metadata.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional


def install_pyxis(
    branch: Optional[str] = None,
    tag: Optional[str] = None,
    rev: Optional[str] = None,
    path: Optional[str] = None,
):
    """Install pyxis if not available.

    Args:
        branch: Optional branch name to install.
        tag: Optional tag name to install.
        rev: Optional commit revision to install.
    """
    print("Installing pyxis...")
    try:
        cmd = ["cargo", "install"]
        # The pyxis repo contains multiple binary crates; install pyxis-driver
        # specifically so cargo doesn't refuse with "multiple packages found".
        if path:
            cmd.extend(["--path", path])
            print(f"Installing pyxis from path: {path}")
        else:
            cmd.extend(["--git", "https://github.com/ferrobrew/pyxis.git"])
            if branch:
                cmd.extend(["--branch", branch])
                print(f"Installing pyxis from branch: {branch}")
            elif tag:
                cmd.extend(["--tag", tag])
                print(f"Installing pyxis from tag: {tag}")
            elif rev:
                cmd.extend(["--rev", rev])
                print(f"Installing pyxis from revision: {rev}")
        cmd.append("pyxis-driver")
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error installing pyxis: {e}", file=sys.stderr)
        sys.exit(1)


def find_pyxis_toml_files(root_dir: Path) -> List[Path]:
    """Find all pyxis.toml files in the repository."""
    return list(root_dir.rglob("pyxis.toml"))


def build_pyxis_project(input_dir: Path, output_dir: Path, backend: str) -> bool:
    """Build a pyxis project and return True if successful."""
    # On Windows, ensure UTF-8 encoding for subprocess output
    env = os.environ.copy()
    if platform.system() == "Windows":
        env["PYTHONIOENCODING"] = "utf-8"
        # Ensure console can handle UTF-8
        if sys.stderr.isatty():
            try:
                # Try to set console code page to UTF-8
                import ctypes

                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleOutputCP(65001)  # UTF-8 code page
            except Exception:
                pass  # Ignore if we can't set it

    try:
        subprocess.run(
            [
                "pyxis",
                "build",
                "--backend",
                backend,
                str(input_dir),
                str(output_dir) + "/",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error building {input_dir}:", file=sys.stderr)
        # Ensure stderr can handle UTF-8 output on Windows
        if platform.system() == "Windows":
            try:
                if sys.stderr.encoding != "utf-8":
                    sys.stderr.reconfigure(encoding="utf-8")
            except Exception:
                pass  # Ignore if reconfiguration fails
        if e.stderr:
            print(e.stderr, file=sys.stderr, end="")
        if e.stdout:
            print(e.stdout, file=sys.stderr, end="")
        return False


def get_project_name(json_file: Path) -> str:
    """Extract project_name from the generated JSON file."""
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("project_name", "")
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error reading {json_file}: {e}", file=sys.stderr)
        return ""


def get_pyxis_version(json_file: Path) -> Optional[str]:
    """Extract the pyxis version that generated this doc, if present.

    Older documents (schema < v6) don't carry `pyxis_version`; return None
    so the index omits the field rather than lying with a placeholder.
    """
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("pyxis_version")
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error reading {json_file}: {e}", file=sys.stderr)
        return None


def get_git_last_modified(path: Path) -> Optional[datetime]:
    """Get the last modified timestamp from Git for a directory.
    Returns None if no Git history is available."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None

    git_timestamp_str = result.stdout.strip()
    if not git_timestamp_str:
        return None

    try:
        # Parse the timestamp (handles various ISO 8601 formats)
        git_dt = datetime.fromisoformat(git_timestamp_str.replace("Z", "+00:00"))
    except ValueError:
        return None

    # Convert to UTC if it has timezone info, otherwise assume UTC
    if git_dt.tzinfo is None:
        return git_dt.replace(tzinfo=timezone.utc)
    return git_dt.astimezone(timezone.utc)


# --- Build verification (compile the generated Rust/C++ output) ----------
#
# The definitions describe Windows game memory and assume the consuming crate
# provides the external dependencies their `backend` glue references. The defs
# can't declare these themselves, so the check harness supplies them per
# project. `paste` is a codegen support crate needed by any output;
# everything else is project-specific (see RUST_CHECK_OVERRIDES) so a project
# isn't checked against dependencies it doesn't use.
#
# This per-project mapping is a deliberate bodge for the check harness only;
# a future iteration can derive it from the definitions instead.
_WINDOWS_DEP = """\
windows = { version = "0.58", features = [
    "Win32_Foundation",
    "Win32_Graphics_Direct3D10",
    "Win32_Graphics_Direct3D11",
    "Win32_Graphics_Dxgi",
    "Win32_Graphics_Gdi",
    "Win32_Storage_FileSystem",
    "Win32_System_Console",
    "Win32_System_Diagnostics_Debug",
    "Win32_System_Kernel",
    "Win32_System_LibraryLoader",
    "Win32_System_SystemServices",
    "Win32_System_Threading",
    "Win32_UI_Input_KeyboardAndMouse",
    "Win32_UI_WindowsAndMessaging",
] }
"""

_GLAM_DEP = 'glam = { version = "0.27", optional = true }\n'
_BEVY_DEP = 'bevy_math = { version = "0.14", default-features = false, optional = true }\n'

_GLAM_BEVY_DEPS = _GLAM_DEP + _BEVY_DEP

_GLAM_BEVY_FEATURES = """\
[features]
glam = ["dep:glam"]
bevy_math = ["dep:bevy_math"]
"""

_GLAM_FEATURES = '[features]\nglam = ["dep:glam"]\n'

# Per-project Rust check configuration, keyed by the project's path relative
# to `projects/`. `dependencies` / `features` are spliced into the throwaway
# crate's Cargo.toml; `enable` lists the cargo features to turn on.
RUST_CHECK_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "JustCause2/Steam/251893": {
        "dependencies": _WINDOWS_DEP + _GLAM_BEVY_DEPS,
        "features": _GLAM_BEVY_FEATURES,
        "enable": ["glam", "bevy_math"],
    },
    "MadMax/GOG/54162766550729305": {
        "dependencies": _WINDOWS_DEP + _GLAM_BEVY_DEPS,
        "features": _GLAM_BEVY_FEATURES,
        "enable": ["glam", "bevy_math"],
    },
    "JustCause3/Steam/1227440": {
        "dependencies": _WINDOWS_DEP + _GLAM_DEP,
        "features": _GLAM_FEATURES,
        "enable": ["glam"],
    },
    "JustCause3/Steam/20206564": {
        "dependencies": _WINDOWS_DEP + _GLAM_DEP,
        "features": _GLAM_FEATURES,
        "enable": ["glam"],
    },
}

_DEFAULT_RUST_CONFIG: Dict[str, Any] = {"dependencies": "", "features": "", "enable": []}


def rust_check_cargo_toml(crate_name: str, config: Dict[str, Any]) -> str:
    """Assemble a throwaway-crate Cargo.toml from a per-project config. The
    crate name is per-project so multiple checks can share a CARGO_TARGET_DIR
    (for dependency reuse) without colliding on the same package artifact."""
    return (
        "[package]\n"
        f'name = "{crate_name}"\n'
        'version = "0.0.0"\n'
        'edition = "2021"\n\n'
        f"{config['features']}\n"
        "[dependencies]\n"
        'paste = "1.0"\n'
        f"{config['dependencies']}"
    )


def read_pointer_size(toml_file: Path) -> int:
    """Read `pointer_size` from a project's pyxis.toml."""
    for line in toml_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("pointer_size"):
            return int(line.split("=", 1)[1].strip())
    raise ValueError(f"no pointer_size in {toml_file}")


def rust_target_for_pointer_size(pointer_size: int) -> str:
    """The definitions describe Windows game memory, so they're checked
    against a Windows target whose pointer width matches the project."""
    return "i686-pc-windows-msvc" if pointer_size == 4 else "x86_64-pc-windows-msvc"


def generate_rust_crate(
    rel_path: str, input_dir: Path, work_dir: Path
) -> Optional[Dict[str, Any]]:
    """Generate a project's Rust output into a crate directory and write its
    Cargo.toml. Returns the crate metadata (name, target, features to enable)
    for later checking, or None if generation failed."""
    pointer_size = read_pointer_size(input_dir / "pyxis.toml")
    target = rust_target_for_pointer_size(pointer_size)
    config = RUST_CHECK_OVERRIDES.get(rel_path, _DEFAULT_RUST_CONFIG)
    crate_name = "check-" + rel_path.lower().replace("/", "-").replace("_", "-")

    src_dir = work_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    # Generate at the crate root (root module -> src/lib.rs), matching how a
    # consumer mounts the whole project.
    gen = subprocess.run(
        [
            "pyxis", "build", "--backend", "rust",
            str(input_dir), str(src_dir) + "/",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if gen.returncode != 0:
        print(gen.stderr, file=sys.stderr, end="")
        return None
    (work_dir / "Cargo.toml").write_text(
        rust_check_cargo_toml(crate_name, config), encoding="utf-8"
    )
    return {"crate_name": crate_name, "target": target, "enable": config["enable"]}


def check_rust_crate(
    workspace_dir: Path, crate_meta: Dict[str, Any], target_dir: Path
) -> bool:
    """`cargo check` a single crate from within the workspace. The workspace
    root is used as the cwd so Cargo resolves against the virtual workspace
    Cargo.toml rather than walking up the directory tree."""
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    cmd = [
        "cargo", "check",
        "--target", crate_meta["target"],
        "-p", crate_meta["crate_name"],
    ]
    if crate_meta["enable"]:
        cmd += ["--features", ",".join(crate_meta["enable"])]
    check = subprocess.run(cmd, cwd=workspace_dir, env=env)
    return check.returncode == 0


def workspace_cargo_toml(members: List[str]) -> str:
    """Assemble a virtual workspace Cargo.toml listing all member crates.
    This prevents Cargo from walking up the directory tree to find a parent
    workspace, which could cause conflicts when the check temp directory
    happens to live inside another Cargo workspace."""
    members_str = ", ".join(f'"{m}"' for m in members)
    return (
        "[workspace]\n"
        f"members = [{members_str}]\n"
        'resolver = "2"\n'
    )


def check_cpp_build(input_dir: Path, work_dir: Path) -> Optional[bool]:
    """Generate a project's C++ output and build it with CMake. The build
    toolchain is the environment's responsibility (vanilla MSVC on Windows,
    or clang-cl + xwin on Linux); point at one per architecture via
    `PYXIS_CHECK_CMAKE_TOOLCHAIN_X86` / `_X64`. Returns None (skipped) when no
    toolchain is configured for the project's architecture and the host can't
    build MSVC C++ on its own."""
    pointer_size = read_pointer_size(input_dir / "pyxis.toml")
    arch = "X86" if pointer_size == 4 else "X64"
    toolchain = os.environ.get(f"PYXIS_CHECK_CMAKE_TOOLCHAIN_{arch}")
    if toolchain is None and platform.system() != "Windows":
        print(f"  (skipped: no PYXIS_CHECK_CMAKE_TOOLCHAIN_{arch} and host isn't Windows)")
        return None

    out_dir = work_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    gen = subprocess.run(
        ["pyxis", "build", "--backend", "cpp", str(input_dir), str(out_dir) + "/"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if gen.returncode != 0:
        print(gen.stderr, file=sys.stderr, end="")
        return False

    build_dir = work_dir / "build"
    configure = ["cmake", "-S", str(out_dir), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release"]
    if toolchain:
        configure.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain}")
    elif platform.system() == "Windows":
        # Native MSVC: select the target architecture for the Visual Studio
        # generator (32-bit projects must build as Win32, not the x64 host).
        configure += ["-A", "Win32" if arch == "X86" else "x64"]
    # The xwin toolchains read XWIN_ROOT; forward it if the environment set it.
    if os.environ.get("XWIN_ROOT"):
        configure.append(f"-DXWIN_ROOT={os.environ['XWIN_ROOT']}")
    if subprocess.run(configure).returncode != 0:
        return False
    # --config selects the build type for multi-config generators (Visual
    # Studio); it's ignored by single-config ones, so it's safe to always pass.
    built = subprocess.run(
        ["cmake", "--build", str(build_dir), "--parallel", "--config", "Release"]
    )
    return built.returncode == 0


def check_all_builds(
    repo_root: Path, backends: List[str], output_dir: Optional[Path] = None
) -> None:
    """Compile-check the generated output for every project. Exits non-zero
    if any project fails to build. If output_dir is provided, artifacts are
    persisted there; otherwise a temp directory is used and deleted on exit."""
    import tempfile
    import shutil

    project_dir = repo_root / "projects"
    toml_files = sorted(find_pyxis_toml_files(project_dir))
    failures: List[str] = []

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        tmp_path = output_dir
        cleanup = False
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="pyxis-defs-check-")
        tmp_path = Path(tmp_ctx.__enter__())
        cleanup = True

    try:
        target_dir = tmp_path / "target"

        # --- Rust: generate all crates first, then check as a workspace ---
        # Generating first lets us write a virtual workspace Cargo.toml that
        # pins every member explicitly, preventing Cargo from walking up the
        # tree and resolving against an unrelated parent workspace.
        rust_crates: List[Dict[str, Any]] = []
        if "rust" in backends:
            for toml_file in toml_files:
                input_dir = toml_file.parent
                rel_path = input_dir.relative_to(project_dir).as_posix()
                name = rel_path.replace("/", "_")
                work_dir = tmp_path / f"{name}-rust"
                print(f"== generating Rust crate: {name} ==")
                crate_meta = generate_rust_crate(rel_path, input_dir, work_dir)
                if crate_meta is None:
                    failures.append(f"{name} (rust)")
                else:
                    rust_crates.append({**crate_meta, "name": name})

            if rust_crates:
                member_dirs = [f"{c['name']}-rust" for c in rust_crates]
                (tmp_path / "Cargo.toml").write_text(
                    workspace_cargo_toml(member_dirs), encoding="utf-8"
                )
                for crate in rust_crates:
                    print(f"== checking Rust build: {crate['name']} ==")
                    if not check_rust_crate(tmp_path, crate, target_dir):
                        failures.append(f"{crate['name']} (rust)")

        # --- C++: check each project independently (no workspace concept) ---
        if "cpp" in backends:
            for toml_file in toml_files:
                input_dir = toml_file.parent
                rel_path = input_dir.relative_to(project_dir).as_posix()
                name = rel_path.replace("/", "_")
                print(f"== checking C++ build: {name} ==")
                work_dir = tmp_path / f"{name}-cpp"
                if check_cpp_build(input_dir, work_dir) is False:
                    failures.append(f"{name} (cpp)")

        if failures:
            print("\nBuild check failures:", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
            if output_dir is not None:
                print(f"\nOutput preserved at: {output_dir}", file=sys.stderr)
            sys.exit(1)
        print("\nAll build checks passed.")
        if output_dir is not None:
            print(f"Output preserved at: {output_dir}")
    finally:
        if cleanup:
            tmp_ctx.__exit__(None, None, None)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Build pyxis projects and generate index.json"
    )
    parser.add_argument(
        "--branch",
        type=str,
        default=None,
        help="Optional branch name of Pyxis to install",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Optional tag name of Pyxis to install",
    )
    parser.add_argument(
        "--rev",
        type=str,
        default=None,
        help="Optional commit revision of Pyxis to install",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Optional path to Pyxis to install",
    )
    parser.add_argument(
        "--no-install", action="store_true", help="Do not install pyxis"
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="json",
        help="Backend to use for code generation (default: json)",
    )
    parser.add_argument(
        "--check-builds",
        type=str,
        default=None,
        metavar="BACKENDS",
        help="Instead of generating docs, compile-check the generated output "
        "for every project. Comma-separated list of backends (e.g. `rust`).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="When used with --check-builds, persist generated output and build "
        "artifacts to this directory instead of a temp dir that's deleted on exit.",
    )
    args = parser.parse_args()

    specified = sum(
        [
            args.branch is not None,
            args.tag is not None,
            args.rev is not None,
            args.path is not None,
        ]
    )
    if specified > 1:
        parser.error("Only one of --branch, --tag, --rev, or --path can be specified")

    # Check for required tools
    if not args.no_install:
        install_pyxis(branch=args.branch, tag=args.tag, rev=args.rev, path=args.path)

    # Get repository root
    repo_root = Path(__file__).parent.resolve()

    # Build-verification mode: compile-check generated output and exit.
    if args.check_builds:
        backends = [b.strip() for b in args.check_builds.split(",") if b.strip()]
        output_dir = Path(args.output_dir) if args.output_dir else None
        check_all_builds(repo_root, backends, output_dir)
        return

    backend = args.backend

    # For JSON backend, use docs/ directory; otherwise use {backend}/ directory
    if backend == "json":
        output_base_dir = repo_root / "docs"
    else:
        output_base_dir = repo_root / backend
    output_base_dir.mkdir(exist_ok=True)

    # Find all pyxis.toml files
    project_dir = repo_root / "projects"
    toml_files = find_pyxis_toml_files(project_dir)

    if not toml_files:
        print("No pyxis.toml files found.")
        sys.exit(1)

    # Build array of (output_name, toml_path) tuples
    projects: List[tuple[str, Path]] = []
    for toml_file in toml_files:
        input_dir = toml_file.parent
        rel_path = input_dir.relative_to(project_dir)
        output_name = str(rel_path).replace(os.sep, "_").replace("/", "_")
        projects.append((output_name, toml_file))

    # Sort by output_name
    projects.sort(key=lambda x: x[0])

    documents: List[Dict[str, Any]] = []

    # Process each project
    for output_name, toml_file in projects:
        input_dir = toml_file.parent
        output_dir = output_base_dir / output_name

        print(f"Building {input_dir} -> {output_dir}")

        # Build with pyxis
        if not build_pyxis_project(input_dir, output_dir, backend):
            print(f"Error: Failed to build {input_dir}", file=sys.stderr)
            sys.exit(1)

        # For JSON backend, collect metadata for index generation
        if backend == "json":
            # Extract project_name from the generated JSON
            json_file = output_dir / "output.json"
            if not json_file.exists():
                print(f"Error: {json_file} not found after build", file=sys.stderr)
                sys.exit(1)

            project_name = get_project_name(json_file)
            if not project_name:
                print(
                    f"Error: Could not extract project_name from {json_file}",
                    file=sys.stderr,
                )
                sys.exit(1)

            # Get last modified timestamp from Git
            last_modified_dt = get_git_last_modified(input_dir)
            # Convert to ISO8601 string if available, otherwise None
            last_modified_iso8601 = (
                last_modified_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                if last_modified_dt is not None
                else None
            )

            # Which pyxis generated this doc (None for schema < v6).
            pyxis_version = get_pyxis_version(json_file)

            # Get relative path to JSON from repo root
            json_path = json_file.relative_to(repo_root)

            # Add document to list
            document = {
                "name": project_name,
                "path": str(json_path).replace(
                    "\\", "/"
                ),  # Use forward slashes for paths
                "last_modified_iso8601": last_modified_iso8601,
            }
            if pyxis_version is not None:
                document["pyxis_version"] = pyxis_version
            documents.append(document)

    # Generate index.json only for JSON backend
    if backend == "json":
        # Generate current timestamp in ISO 8601 format
        generated_iso8601 = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Build the index.json
        index_data = {"generated_iso8601": generated_iso8601, "docs": documents}

        index_file = output_base_dir / "index.json"
        try:
            with open(index_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
        except (IOError, OSError) as e:
            print(f"Error: Failed to write {index_file}: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"Index generated at {index_file}")


if __name__ == "__main__":
    main()
