"""
Virtual environment package manager for Blender 5.
====================================================
Copy this file to your project folder and import it at the top of your script.

Usage:
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from ensure_packages import ensure_packages

    ensure_packages(["shapely", "requests", "numpy"])
    # Creates .venv/ if it doesn't exist, installs missing packages,
    # and adds the venv's site-packages to sys.path.

Notes:
    - The venv is created at .venv/ inside the same directory as the script.
    - The venv is built using Blender 5's Python (python3.11).
    - Already-installed packages are not reinstalled.
"""

import sys
import os
import subprocess
import importlib.util
from pathlib import Path


def _get_blender_python() -> Path:
    """Return the path to Blender 5's python3.11 executable."""
    if sys.platform == "darwin":
        candidates = [
            Path("/Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11"),
        ]
    elif sys.platform == "win32":
        candidates = [
            Path(r"C:\Program Files\Blender Foundation\Blender 5.0\5.0\python\bin\python.exe"),
        ]
    else:
        # Linux (snap / manual install)
        candidates = [
            Path("/usr/share/blender/5.0/python/bin/python3.11"),
            Path(os.path.expanduser("~/blender-5.0/5.0/python/bin/python3.11")),
        ]

    for p in candidates:
        if p.exists():
            return p

    # Fallback: current sys.executable (Blender's internal Python)
    return Path(sys.executable)


def _get_venv_python(venv_dir: Path) -> Path:
    """Return the path to the python executable inside the venv."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python3"


def _get_venv_site_packages(venv_dir: Path) -> Path:
    """Return the path to the site-packages directory inside the venv."""
    if sys.platform == "win32":
        return venv_dir / "Lib" / "site-packages"
    # Fixed to python3.11
    return venv_dir / "lib" / "python3.11" / "site-packages"


def ensure_packages(packages: list[str], script_file: str = None) -> None:
    """
    Ensure the given packages are available in the venv.

    Args:
        packages: List of pip package names to install (e.g. ["shapely", "requests"])
        script_file: Path to the calling script file. Used to determine where to
                     create the venv. Defaults to the caller's __file__.
    """
    if script_file is None:
        import inspect
        frame = inspect.stack()[1]
        script_file = frame.filename

    script_dir = Path(script_file).parent
    venv_dir = script_dir / ".venv"

    # --- 1. Create venv if needed ---
    venv_python = _get_venv_python(venv_dir)
    if not venv_python.exists():
        blender_python = _get_blender_python()
        print(f"[ensure_packages] Creating venv at: {venv_dir}")
        subprocess.run(
            [str(blender_python), "-m", "venv", str(venv_dir)],
            check=True,
        )

    # --- 2. Add site-packages to sys.path ---
    site_packages = _get_venv_site_packages(venv_dir)
    site_packages_str = str(site_packages)
    if site_packages_str not in sys.path:
        sys.path.insert(0, site_packages_str)

    # --- 3. Install missing packages ---
    missing = []
    for pkg in packages:
        # Handle packages where pip name differs from import name (e.g. Pillow -> PIL)
        import_name = _package_to_import_name(pkg)
        if importlib.util.find_spec(import_name) is None:
            missing.append(pkg)

    if missing:
        print(f"[ensure_packages] Installing: {missing}")
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
        )
        subprocess.run(
            [str(venv_python), "-m", "pip", "install"] + missing,
            check=True,
        )
        print(f"[ensure_packages] Done: {missing}")
    else:
        print(f"[ensure_packages] All packages present: {packages}")


def _package_to_import_name(package: str) -> str:
    """Map a pip package name to its import name for common cases."""
    mapping = {
        "pillow": "PIL",
        "opencv-python": "cv2",
        "scikit-learn": "sklearn",
        "beautifulsoup4": "bs4",
        "pyyaml": "yaml",
    }
    return mapping.get(package.lower(), package.replace("-", "_"))
