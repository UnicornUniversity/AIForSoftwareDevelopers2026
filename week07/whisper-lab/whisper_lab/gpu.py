"""Make pip-installed NVIDIA CUDA libraries visible to CTranslate2 on Windows.

`pip install -r requirements-cuda.txt` puts cublas, cudnn, and the CUDA runtime
under ``site-packages/nvidia/<package>/bin``. Windows does not search those
directories by default, and CTranslate2 loads the DLLs lazily at the first
encode/decode call -- not when the model is constructed. Without this, a GPU
run loads fine and then dies mid-transcription with:

    RuntimeError: Library cublas64_12.dll is not found or cannot be loaded

The fix is to register each directory with ``os.add_dll_directory`` (and add it
to PATH for the older loader paths CTranslate2 still uses). The returned
handles must stay alive for as long as the process runs, so we keep them in a
module-level list.

On macOS and Linux the wheels install into a location the dynamic linker
already understands, so this is a no-op there.
"""

from __future__ import annotations

import os
import site
import sys
from pathlib import Path

# os.add_dll_directory returns a handle that closes the directory when garbage
# collected; keeping it referenced here keeps the DLL search path active.
_DLL_DIRECTORY_HANDLES: list = []
_REGISTERED: set[Path] = set()


def _site_package_dirs() -> list[Path]:
    """Every site-packages directory Python might use for this interpreter."""
    candidates: list[Path] = []
    try:
        candidates.extend(Path(p) for p in site.getsitepackages())
    except AttributeError:
        pass

    user_site = site.getusersitepackages()
    if user_site:
        candidates.append(Path(user_site))

    # A virtualenv puts packages in a location that is not always reported by
    # site.getsitepackages(), so derive it from the interpreter as a fallback.
    candidates.append(Path(sys.base_prefix) / "Lib" / "site-packages")
    candidates.append(Path(sys.prefix) / "Lib" / "site-packages")

    return [path for path in candidates if path.is_dir()]


def prepare_cuda_dlls() -> list[Path]:
    """Register every nvidia/*/bin directory with the Windows DLL loader.

    Returns the directories that were registered, which is handy for logging
    and for tests. Safe to call repeatedly.
    """
    if sys.platform != "win32":
        return []

    prepared: list[Path] = []
    for site_dir in _site_package_dirs():
        for dll_dir in sorted((site_dir / "nvidia").glob("*/bin")):
            if not dll_dir.is_dir() or dll_dir in _REGISTERED:
                continue
            try:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(dll_dir)))
            except OSError:
                continue
            os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
            _REGISTERED.add(dll_dir)
            prepared.append(dll_dir)

    return prepared
