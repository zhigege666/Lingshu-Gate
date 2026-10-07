"""Safe deterministic process failure: first local build fails, next build succeeds."""
import json
import sys
import zipfile
from pathlib import Path

archive_path = Path(sys.argv[1])
marker = archive_path.parent / "synthetic-build-once.marker"
script = (
    "const fs = require('node:fs');\n"
    f"const marker = {json.dumps(str(marker))};\n"
    "if (!fs.existsSync(marker)) { fs.writeFileSync(marker, 'synthetic'); "
    "console.error('Synthetic first build failure'); process.exit(17); }\n"
    "console.log('Synthetic retry build succeeded');\n"
)
files = {
    "package.json": json.dumps({"name": "synthetic-build-recovery", "version": "0.0.1",
                                "main": "index.js", "scripts": {"build": "node build.cjs"}}),
    "index.js": "process.stdin.resume();\n",
    "build.cjs": script,
}
with zipfile.ZipFile(archive_path, "w") as archive:
    for name, contents in sorted(files.items()):
        archive.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), contents)
