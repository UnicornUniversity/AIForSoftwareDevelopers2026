from __future__ import annotations

import os
import subprocess
import sys


def clean_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("UDA_", "LANGFUSE_"))
    }


def test_package_imports_without_environment() -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import uda, uda.config, uda.cli"],
        capture_output=True,
        text=True,
        env=clean_env(),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_import_does_not_load_langfuse_sdk() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys, uda.cli; print('langfuse' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        env=clean_env(),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
