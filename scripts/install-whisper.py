#!/usr/bin/env python3
"""
Sarthak AI — Whisper STT installer (cross-platform, no dependencies).

Downloads whisper-cli and a GGML model so Sarthak can transcribe audio/video
notes locally without sending data to any cloud service.

Usage:
    python scripts/install-whisper.py              # installs base.en model
    WHISPER_MODEL=small.en python scripts/install-whisper.py

For hardware-optimised setup (CUDA / Metal / OpenBLAS / CoreML) check out:
    https://github.com/ggml-org/whisper.cpp
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

MODEL      = os.environ.get("WHISPER_MODEL", "base.en")
INSTALL_DIR = Path.home() / ".sarthak_ai"
MODELS_DIR  = INSTALL_DIR / "whisper_models"
BIN_DIR     = Path.home() / ".local" / "bin"   # Linux/macOS
WIN_BIN_DIR = INSTALL_DIR / "bin"               # Windows

HUGGINGFACE_MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin"
)
GITHUB_RELEASES_API = "https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest"

# Approximate model sizes for user info
MODEL_SIZES = {
    "tiny":    " ~75 MB",  "tiny.en":    " ~75 MB",
    "base":    "~142 MB",  "base.en":    "~142 MB",
    "small":   "~466 MB",  "small.en":   "~466 MB",
    "medium":  "~1.5 GB",  "medium.en":  "~1.5 GB",
    "large-v3":"~3.1 GB",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def info(msg: str)  -> None: print(f"  > {msg}")
def ok(msg: str)    -> None: print(f"  + {msg}")
def warn(msg: str)  -> None: print(f"  ! {msg}", file=sys.stderr)
def fail(msg: str)  -> None: sys.exit(f"\n  ✗ {msg}")


def download(url: str, dest: Path, label: str = "") -> None:
    """Download url → dest with a simple progress indicator."""
    label = label or dest.name
    info(f"Downloading {label} ...")
    def _progress(count, block, total):
        if total > 0:
            pct = min(100, count * block * 100 // total)
            print(f"\r    {pct:3d}%", end="", flush=True)
    try:
        urllib.request.urlretrieve(url, dest, reporthook=_progress)
        print()  # newline after progress
    except Exception as exc:
        fail(f"Download failed: {exc}\n    URL: {url}")


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


# ── Step 1: Install whisper-cli binary ────────────────────────────────────────

def whisper_already_installed() -> bool:
    return bool(shutil.which("whisper-cli") or shutil.which("whisper"))


def install_binary_macos() -> bool:
    """macOS: try Homebrew first, then fall back to build from source."""
    if shutil.which("brew"):
        info("Installing via Homebrew: brew install whisper-cpp")
        r = subprocess.run(["brew", "install", "whisper-cpp"])
        if r.returncode == 0:
            return True
        warn("Homebrew install failed.")
    return _build_from_source()


def install_binary_linux() -> bool:
    """Linux: build from source (needs git + cmake or make + a C++ compiler)."""
    for cmd in ("git", "make"):
        if not shutil.which(cmd):
            warn(f"'{cmd}' not found — needed to build whisper.cpp")
            warn("Install build tools (e.g. sudo apt install git build-essential cmake)")
            return False
    return _build_from_source()


def _build_from_source() -> bool:
    build_dir = Path(tempfile.mkdtemp()) / "whisper.cpp"
    info("Cloning whisper.cpp (shallow) ...")
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "https://github.com/ggml-org/whisper.cpp", str(build_dir)]
    )
    if r.returncode != 0:
        warn("git clone failed.")
        return False

    # Try cmake first, fall back to plain make
    built = False
    if shutil.which("cmake"):
        bld = build_dir / "build"
        r1 = subprocess.run(
            ["cmake", "-B", str(bld), "-S", str(build_dir),
             "-DCMAKE_BUILD_TYPE=Release",
             "-DWHISPER_BUILD_TESTS=OFF",
             "-DWHISPER_BUILD_EXAMPLES=ON"],
            capture_output=True,
        )
        r2 = subprocess.run(
            ["cmake", "--build", str(bld), "--config", "Release",
             "-j", str(os.cpu_count() or 2)],
            capture_output=True,
        )
        cli = bld / "bin" / "whisper-cli"
        if r2.returncode == 0 and cli.exists():
            _copy_to_bin(cli)
            built = True

    if not built:
        r = subprocess.run(
            ["make", "-j", str(os.cpu_count() or 2)],
            cwd=build_dir, capture_output=True,
        )
        # older repos emit 'main', newer emit 'whisper-cli'
        for name in ("whisper-cli", "main"):
            cli = build_dir / name
            if r.returncode == 0 and cli.exists():
                _copy_to_bin(cli)
                built = True
                break

    if not built:
        warn("Build failed — check that you have g++/clang + cmake or make installed.")
    return built


def _copy_to_bin(src: Path) -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    dest = BIN_DIR / "whisper-cli"
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    ok(f"whisper-cli installed → {dest}")
    _ensure_bin_in_path()


def _ensure_bin_in_path() -> None:
    bin_str = str(BIN_DIR)
    if bin_str not in os.environ.get("PATH", ""):
        warn(f"{bin_str} is not in PATH.")
        info(f"Add to your shell profile:  export PATH=\"$PATH:{bin_str}\"")


def install_binary_windows() -> bool:
    """Windows: download pre-built zip from GitHub releases."""
    WIN_BIN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        info("Fetching latest whisper.cpp release info ...")
        release = fetch_json(GITHUB_RELEASES_API)
        asset = next(
            (a for a in release["assets"] if "win" in a["name"].lower() and "x64" in a["name"].lower() and a["name"].endswith(".zip")),
            next((a for a in release["assets"] if a["name"].endswith(".zip")), None),
        )
        if not asset:
            warn("No Windows zip asset found in latest release.")
            return False

        zip_path = Path(tempfile.mkdtemp()) / "whisper_win.zip"
        download(asset["browser_download_url"], zip_path, asset["name"])
        ext_dir = zip_path.parent / "whisper_win"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(ext_dir)

        exe = next(ext_dir.rglob("whisper-cli.exe"), None)
        if not exe:
            warn("whisper-cli.exe not found in downloaded zip.")
            return False

        dest = WIN_BIN_DIR / "whisper-cli.exe"
        shutil.copy2(exe, dest)
        ok(f"whisper-cli.exe installed → {dest}")
        _add_to_win_path(str(WIN_BIN_DIR))
        return True
    except Exception as exc:
        warn(f"Windows install failed: {exc}")
        return False


def _add_to_win_path(directory: str) -> None:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS)
        current, _ = winreg.QueryValueEx(key, "Path")
        if directory not in current:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, f"{current};{directory}")
            ok(f"Added {directory} to user PATH (restart shell to take effect)")
        winreg.CloseKey(key)
    except Exception:
        warn(f"Could not update PATH automatically. Add manually: {directory}")


# ── Step 2: Download GGML model ───────────────────────────────────────────────

def download_model(model: str) -> bool:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MODELS_DIR / f"ggml-{model}.bin"
    if dest.exists():
        ok(f"Model already present: {dest.name}")
        return True

    size_hint = MODEL_SIZES.get(model, "")
    url = HUGGINGFACE_MODEL_URL.format(model=model)
    info(f"Downloading model '{model}'{size_hint} ...")
    info(f"From: {url}")
    try:
        download(url, dest, f"ggml-{model}.bin")
        ok(f"Model saved: {dest}")
        return True
    except SystemExit:
        warn(f"Model download failed. Run manually:")
        warn(f"  curl -fL {url} -o \"{dest}\"")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    system = platform.system()
    print()
    print("  Sarthak AI — Whisper STT installer")
    print(f"  Platform : {system} ({platform.machine()})")
    print(f"  Model    : {MODEL}")
    print()

    # Step 1: binary
    print("  [1/2] whisper-cli binary")
    if whisper_already_installed():
        ok("whisper-cli already in PATH — skipping")
        binary_ok = True
    elif system == "Darwin":
        binary_ok = install_binary_macos()
    elif system == "Linux":
        binary_ok = install_binary_linux()
    elif system == "Windows":
        binary_ok = install_binary_windows()
    else:
        warn(f"Unsupported platform: {system}")
        binary_ok = False

    if not binary_ok:
        warn("Could not install whisper-cli automatically.")
        print()
        print("  Manual options:")
        print("    macOS  : brew install whisper-cpp")
        print("    Linux  : build from source (see below)")
        print("    Windows: download zip from GitHub releases (see below)")
        print()
        print("  For hardware-optimised setup check out https://github.com/ggml-org/whisper.cpp")
        print()

    # Step 2: model (always attempt — useful even when binary needs manual install)
    print()
    print(f"  [2/2] GGML model  ({MODEL})")
    model_ok = download_model(MODEL)

    # Summary
    print()
    if binary_ok and model_ok:
        print("  ✓ Whisper STT ready.")
        print(f"    Binary : whisper-cli")
        print(f"    Model  : {MODELS_DIR / ('ggml-' + MODEL + '.bin')}")
    else:
        print("  ✗ Setup incomplete — see warnings above.")

    print()
    print("  For hardware-optimised setup check out https://github.com/ggml-org/whisper.cpp")
    print()


if __name__ == "__main__":
    main()
