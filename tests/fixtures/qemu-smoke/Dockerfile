ARG LINGSHU_GATE_PYTHON_IMAGE
FROM ${LINGSHU_GATE_PYTHON_IMAGE}
ARG TARGETARCH
RUN python -c 'import os, platform; expected = {"amd64": "x86_64", "arm64": "aarch64"}[os.environ["TARGETARCH"]]; assert platform.machine() == expected, (platform.machine(), expected); print("QEMU architecture smoke passed:", expected)'
