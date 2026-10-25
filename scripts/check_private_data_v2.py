#!/usr/bin/env python3
"""Reject hard-coded operator account defaults in production Python."""
import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}|(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,55}(?![1-9A-HJ-NP-Za-km-z])")


def violations(root: Path) -> list[str]:
    findings = []
    for path in (root / "src/steuerreport_v2").rglob("*.py"):
        text = path.read_text()
        for match in re.finditer(r"\bDE\d{20}\b|Konto_\d{6,12}", text):
            findings.append(f"{path.relative_to(root)}:{text[:match.start()].count(chr(10)) + 1}:bank_identifier")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if not any(any(word in name.upper() for word in ("WALLET", "ACCOUNT", "ADDRESS")) and any(word in name.upper() for word in ("OWN", "MAIN", "PRIMARY", "DEFAULT", "LEGACY", "STAKING")) for name in names):
                continue
            if "TOKEN" in " ".join(names) or "PROGRAM" in " ".join(names):
                continue
            # Values read through configuration calls are deliberately allowed.
            values = [node.value] if isinstance(node.value, ast.Constant) else list(node.value.keys) if isinstance(node.value, ast.Dict) else list(node.value.elts) if isinstance(node.value, (ast.Set, ast.Tuple, ast.List)) else []
            if any(isinstance(value, ast.Constant) and isinstance(value.value, str) and ADDRESS.search(value.value) for value in values):
                findings.append(f"{path.relative_to(root)}:{node.lineno}:hardcoded_account")
    return sorted(set(findings))


if __name__ == "__main__":
    result = violations(ROOT)
    for finding in result:
        print(finding)
    print(f"privacy_default_violations={len(result)}")
    raise SystemExit(bool(result))
