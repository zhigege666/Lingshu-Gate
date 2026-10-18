# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder specification for native Lingshu Gate releases."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

repository_root = Path(SPECPATH).parent
source_root = repository_root / "src"

datas = collect_data_files("lingshu_gate", include_py_files=False)
datas.append((str(source_root / "lingshu_gate" / "adapters" / "native_executor" / "runner.py"), "lingshu_gate/adapters/native_executor"))
hiddenimports = sorted(set(collect_submodules("lingshu_gate")))
for distribution in ("opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http"):
    datas += copy_metadata(distribution)
for module in ("opentelemetry.exporter.otlp.proto.http.trace_exporter", "opentelemetry.proto.collector.trace",
               "opentelemetry.proto.trace", "opentelemetry.proto.common", "opentelemetry.proto.resource"):
    hiddenimports += collect_submodules(module)
hiddenimports = sorted(set(hiddenimports))
hiddenimports.append("opentelemetry.context.contextvars_context")

analysis = Analysis(
    [str(repository_root / "packaging" / "pyinstaller_entry.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff", "mypy"],
    noarchive=False,
    optimize=1,
)
python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="lingshu-gate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="lingshu-gate",
)
