#!/usr/bin/env python3
"""Compile the reconstructed protos into a FileDescriptorSet the emulator can load.

The output mirrors what the rig extracted from the client (sc_client_descriptors.pb),
so the same server code runs on either. Requires grpcio-tools.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "build" / "sc_reconstructed_descriptors.pb"


def proto_files(*dirs: Path) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        out.extend(sorted(p for p in d.rglob("*.proto")))
    return out


def build(out: Path = DEFAULT_OUT, proto_dirs: list[Path] | None = None) -> Path:
    from grpc_tools import protoc  # imported lazily: only needed to build, not to run

    import grpc_tools

    dirs = proto_dirs or [ROOT / "protos"]
    wkt_include = Path(grpc_tools.__file__).parent / "_proto"
    files = proto_files(*dirs)
    if not files:
        raise SystemExit(f"no .proto files under {dirs}")
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["protoc"]
    args += [f"-I{d}" for d in dirs]
    args += [f"-I{wkt_include}", "--include_imports", f"--descriptor_set_out={out}"]
    args += [str(f) for f in files]
    rc = protoc.main(args)
    if rc != 0:
        raise SystemExit(f"protoc failed with code {rc}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--protos", type=Path, action="append", help="proto root(s); default ./protos")
    ns = ap.parse_args(argv)
    out = build(ns.out, ns.protos)
    print(f"wrote {out} ({os.path.getsize(out)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
