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

            # Get relative path to JSON from repo root
            json_path = json_file.relative_to(repo_root)

            # Add document to list
            documents.append(
                {
                    "name": project_name,
                    "path": str(json_path).replace(
                        "\\", "/"
                    ),  # Use forward slashes for paths
                    "last_modified_iso8601": last_modified_iso8601,
                }
            )

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
