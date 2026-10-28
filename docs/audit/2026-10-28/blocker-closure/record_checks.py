"""Originalausgaben der lokalen Build-/Drift-/Privacychecks dokumentieren."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[4]
CHECKS = [
    ("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"], ROOT),
    ("independent-baseline", [sys.executable, "scripts/check_reference_baseline_v2.py"], ROOT),
    ("private-defaults", [sys.executable, "scripts/check_private_data_v2.py"], ROOT),
    ("openapi-drift", [sys.executable, "scripts/export_openapi_v2.py", "--check"], ROOT),
    ("endpoint-drift", [sys.executable, "scripts/generate_api_endpoint_reference_v2.py", "--check"], ROOT),
    ("import-docs-drift", [sys.executable, "scripts/generate_import_format_docs_v2.py", "--check"], ROOT),
    ("ai-guide-drift", [sys.executable, "scripts/generate_ai_usage_guide_v2.py", "--check"], ROOT),
    ("view-state", ["node", "scripts/check_workspace_state_v2.cjs"], ROOT),
    ("frontend-build", ["npm", "run", "build"], ROOT / "frontend"),
]


def main():
    results = []
    for name, command, cwd in CHECKS:
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=300)
        results.append({"name": name, "command": command, "cwd": str(cwd.relative_to(ROOT)),
            "started_at": started, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    with Path("/tmp/sr-blockers-cli-checks.json").open("x") as stream:
        json.dump(results, stream, indent=2)
        stream.write("\n")
    print(json.dumps({row["name"]: row["exit_code"] for row in results}))
    return int(any(row["exit_code"] != 0 for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
