"""Independent file-result checks; never drives Workflow state or evaluates reports."""

import ast
import os
import subprocess
import sys
from pathlib import Path


def check_calculator(folder: Path) -> list[str]:
    """Run independent arithmetic vectors; do not trust the agent's own tests."""
    try:
        tree = ast.parse((folder / "calculator.py").read_text(encoding="utf-8"))
        if any(not isinstance(node, ast.FunctionDef) for node in tree.body):
            return ["calculator.py must contain only the pure total function"]
        if len(tree.body) != 1 or tree.body[0].name != "total":
            return ["calculator.py must define total(rows)"]
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Attribute, ast.Global, ast.Nonlocal)):
                return ["calculator.py violates the pure-function contract"]
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                return ["calculator.py contains forbidden interpreter access"]
            if isinstance(node, ast.Call) and (
                not isinstance(node.func, ast.Name)
                or node.func.id not in {"sum", "int", "len", "range", "type", "ValueError"}
            ):
                return ["calculator.py calls outside its pure arithmetic contract"]
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "type"
                    and (len(node.args) != 1 or node.keywords)):
                return ["calculator.py may use type only for input validation"]
        # Restricted builtins plus a separate, time-bounded process. This is a
        # contract check, not a claim that Python AST validation is an OS sandbox.
        worker = """import json,sys
source=open(sys.argv[1],encoding='utf-8').read()
scope={'__builtins__':{'sum':sum,'int':int,'len':len,'range':range,'type':type,'ValueError':ValueError}}
exec(compile(source,sys.argv[1],'exec'),scope)
for rows in ([],[{'qty':2,'price_cents':101}],[{'qty':0,'price_cents':99}],
 [{'qty':3,'price_cents':7},{'qty':4,'price_cents':11}],
 [{'qty':1,'price_cents':0}],[{'qty':10000,'price_cents':99999}]):
 expected=sum(row['qty']*row['price_cents'] for row in rows)
 actual=scope['total'](rows)
 assert type(actual) is int and actual==expected,(actual,expected)
print('6 independent arithmetic vectors PASS')
"""
        environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", worker, str(folder / "calculator.py")],
            cwd=folder,
            env=environment,
            capture_output=True,
            timeout=5,
            check=False,
        )
        return [] if result.returncode == 0 else ["Independent arithmetic vectors failed"]
    except (OSError, SyntaxError, subprocess.TimeoutExpired):
        return ["Independent arithmetic check could not complete"]
