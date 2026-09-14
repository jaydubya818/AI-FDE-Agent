from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_generated_web_contract_matches_backend_models() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_web_contract.py", "--check"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_vercel_build_is_pinned_to_the_fail_closed_hosted_demo() -> None:
    config = json.loads(Path("apps/web/vercel.json").read_text())

    assert config["buildCommand"] == (
        "NEXT_PUBLIC_AI_FDE_HOSTED_DEMO=true "
        "NEXT_PUBLIC_AI_FDE_API_URL=https://api.ai-fde.invalid/api "
        "pnpm run build"
    )
