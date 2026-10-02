"""Create the reviewed, dependency-free browser delivery fixture without executing its source."""
import ast
import sys
import zipfile
from pathlib import Path

source = Path(__file__).resolve().parents[2] / "tests" / "test_real_delivery_journey.py"
module = ast.parse(source.read_text())
server = next(ast.literal_eval(node.value) for node in module.body
              if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "SYNTHETIC_SERVER" for target in node.targets))
with zipfile.ZipFile(sys.argv[1], "w") as archive:
    entry = zipfile.ZipInfo("server.py", (2026, 1, 1, 0, 0, 0))
    archive.writestr(entry, server)
    archive.writestr(zipfile.ZipInfo("pyproject.toml", (2026, 1, 1, 0, 0, 0)),
                     '[project]\nname = "synthetic-browser-delivery"\nversion = "0.0.1"\n')
