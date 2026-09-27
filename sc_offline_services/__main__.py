"""CLI: python -m sc_offline_services [options]"""
from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
import time
from pathlib import Path

from .admin import AdminServer
from .descriptors import DescriptorSet
from .fixtures import Fixtures
from .server import Emulator, ServerConfig
from .state import RingLogHandler

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESCRIPTORS = ROOT / "build" / "sc_reconstructed_descriptors.pb"
DEFAULT_FIXTURES = ROOT / "fixtures" / "offline_services.json"


def _setup_logging(level: int, log_file: Path | None) -> RingLogHandler:
    fmt = logging.Formatter("%(asctime)s.%(msecs)03dZ %(levelname)-7s %(name)s %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")
    fmt.converter = time.gmtime
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(fmt)
    root.addHandler(stderr)
    ring = RingLogHandler()
    ring.setFormatter(fmt)
    root.addHandler(ring)
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    return ring


def _ensure_descriptors(path: Path) -> Path:
    if path.exists():
        return path
    if path != DEFAULT_DESCRIPTORS:
        raise SystemExit(f"descriptor set not found: {path}")
    spec = importlib.util.spec_from_file_location("build_descriptor_set", ROOT / "scripts" / "build_descriptor_set.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"descriptor set not found: {path} and the build script is missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    logging.getLogger("scos").info("building %s from ./protos", path)
    return mod.build(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sc_offline_services", description=__doc__)
    ap.add_argument("--descriptors", type=Path, default=DEFAULT_DESCRIPTORS,
                    help="FileDescriptorSet to serve from (the rig's sc_client_descriptors.pb, or the reconstructed build)")
    ap.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    ap.add_argument("--listen", default="127.0.0.1:443", help="the seat; a specific address beside StarBackend's wildcard")
    ap.add_argument("--tls-cert", type=Path, help="leaf PEM (scripts/make_tls.py); with --tls-key enables TLS")
    ap.add_argument("--tls-key", type=Path)
    ap.add_argument("--upstream", default="127.0.0.3:443", help="StarBackend via its wildcard bind; 'none' disables proxying")
    ap.add_argument("--upstream-ca", type=Path, help="StarBackend's CA public PEM; default: system roots")
    ap.add_argument("--upstream-authority", default="localhost", help="name on StarBackend's leaf (SNI/verify)")
    ap.add_argument("--upstream-plaintext", action="store_true")
    ap.add_argument("--admin", default="127.0.0.1:18081", help="admin http address, or 'off'")
    ap.add_argument("--log-file", type=Path, default=ROOT / "server.log")
    ap.add_argument("-v", "--verbose", action="store_true")
    ns = ap.parse_args(argv)

    ring = _setup_logging(logging.DEBUG if ns.verbose else logging.INFO, ns.log_file)
    log = logging.getLogger("scos")

    ds = DescriptorSet.load(_ensure_descriptors(ns.descriptors))
    fixtures = Fixtures(ns.fixtures)
    cfg = ServerConfig(
        listen=ns.listen,
        tls_cert=ns.tls_cert, tls_key=ns.tls_key,
        upstream=None if ns.upstream.lower() == "none" else ns.upstream,
        upstream_plaintext=ns.upstream_plaintext,
        upstream_ca=ns.upstream_ca,
        upstream_authority=ns.upstream_authority or None,
    )
    if (ns.tls_cert is None) != (ns.tls_key is None):
        raise SystemExit("--tls-cert and --tls-key go together")
    if not cfg.tls and cfg.listen.endswith(":443"):
        log.warning("listening on :443 WITHOUT TLS; the client will not speak plaintext on a 443 default")

    emu = Emulator(ds, fixtures, cfg)
    emu.start()
    admin = None
    if ns.admin.lower() != "off":
        host, _, port = ns.admin.rpartition(":")
        admin = AdminServer(host or "127.0.0.1", int(port), hub=emu.hub, fixtures=fixtures, stats=emu.stats, ring=ring)
        admin.start()
    log.info("ready. Ctrl-C to stop.")
    try:
        emu.wait()
    finally:
        if admin:
            admin.stop()
        emu.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
