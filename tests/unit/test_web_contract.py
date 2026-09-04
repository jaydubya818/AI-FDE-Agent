from __future__ import annotations

import subprocess
import sys


def test_generated_web_contract_matches_backend_models() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_web_contract.py", "--check"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
