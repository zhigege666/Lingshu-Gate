# Third-Party Notices

Lingshu Gate uses open-source libraries distributed under their own licenses.
Those licenses apply to the corresponding components and are not replaced by
the Lingshu Gate license.

Release archives include an SPDX 2.3 software bill of materials containing the
resolved dependency names and versions used for that build. Source dependency
locks are maintained in `uv.lock`, `requirements.lock`, and
`web/package-lock.json`.

Direct runtime dependencies include:

| Component | License |
| --- | --- |
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| Pydantic | MIT |
| PyYAML | MIT |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| python-multipart | Apache-2.0 |
| MCP Python SDK | MIT |
| React and React DOM | MIT |
| Radix UI | MIT |
| Lucide | ISC |
| Tailwind CSS | MIT |
| Vite | MIT |
| CPython runtime (native archives) | PSF-2.0 |
| PyInstaller bootloader and runtime hooks (native archives) | GPL-2.0-or-later WITH Bootloader-exception; project packaging code remains Apache-2.0 |

Transitive dependencies are listed in the release SBOM and lockfiles. Release
bundles also include the collected license texts and a machine-readable license
inventory under `licenses/third-party/`; upstream source distributions remain
the authoritative source for component notices.
