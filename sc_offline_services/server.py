"""Assemble the gRPC server: local routes first, passthrough for the rest of the set."""
from __future__ import annotations

import logging
import time
from concurrent import futures
from dataclasses import dataclass
from pathlib import Path

import grpc

from .descriptors import DescriptorSet
from .fixtures import Fixtures
from .handlers import build_local_routes
from .passthrough import Upstream, make_passthrough
from .push import PushHub
from .state import Stats

log = logging.getLogger("scos.server")


@dataclass
class ServerConfig:
    listen: str = "127.0.0.1:443"
    tls_cert: Path | None = None  # leaf chain PEM; with tls_key selects TLS, else plaintext
    tls_key: Path | None = None
    upstream: str | None = "127.0.0.3:443"  # None: answer only the local routes
    upstream_plaintext: bool = False
    upstream_ca: Path | None = None  # StarBackend's CA (public PEM); None uses system roots
    upstream_authority: str | None = "localhost"  # name on StarBackend's leaf
    max_workers: int = 64

    @property
    def tls(self) -> bool:
        return bool(self.tls_cert and self.tls_key)


class RoutingHandler(grpc.GenericRpcHandler):
    """One handler for everything; unknown methods are logged, then UNIMPLEMENTED."""

    def __init__(self, routes: dict[str, grpc.RpcMethodHandler], kinds: dict[str, str], stats: Stats):
        self.routes = routes
        self.kinds = kinds
        self.stats = stats

    def service(self, handler_call_details):
        method = handler_call_details.method
        h = self.routes.get(method)
        if h is None:
            log.warning("UNIMPLEMENTED %s (not in the descriptor set)", method)
            self.stats.record(method, "unknown", "UNIMPLEMENTED")
            return None
        log.debug("RPC %s [%s]", method, self.kinds.get(method, "?"))
        return h


class Emulator:
    def __init__(self, ds: DescriptorSet, fixtures: Fixtures, cfg: ServerConfig):
        self.ds = ds
        self.fixtures = fixtures
        self.cfg = cfg
        self.stats = Stats()
        self.hub = PushHub(ds)
        self.upstream: Upstream | None = None
        self.port: int | None = None

        routes = build_local_routes(ds, fixtures, self.hub, self.stats)
        kinds = {p: "local" for p in routes}
        if cfg.upstream:
            self.upstream = Upstream(cfg.upstream, plaintext=cfg.upstream_plaintext,
                                     root_pem=cfg.upstream_ca, authority=cfg.upstream_authority)
            for path, m in ds.methods.items():
                if path not in routes:
                    routes[path] = make_passthrough(m, self.upstream, self.stats)
                    kinds[path] = "proxy"
        self.routes = routes
        n_local = sum(1 for k in kinds.values() if k == "local")
        log.info("routes: %d local, %d proxied, upstream=%s", n_local, len(routes) - n_local,
                 cfg.upstream or "none")
        for p in sorted(routes):
            log.debug("  %-7s %s", kinds[p], p)

        options = [
            ("grpc.so_reuseport", 0),  # the seat must be an exclusive, specific bind
            ("grpc.max_receive_message_length", 64 * 1024 * 1024),
            ("grpc.max_send_message_length", 64 * 1024 * 1024),
            ("grpc.keepalive_permit_without_calls", 1),
            ("grpc.http2.max_pings_without_data", 0),
        ]
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=cfg.max_workers),
                                  handlers=[RoutingHandler(routes, kinds, self.stats)], options=options)

    def start(self) -> int:
        if self.cfg.tls:
            key = Path(self.cfg.tls_key).read_bytes()
            cert = Path(self.cfg.tls_cert).read_bytes()
            creds = grpc.ssl_server_credentials([(key, cert)])
            self.port = self.server.add_secure_port(self.cfg.listen, creds)
        else:
            self.port = self.server.add_insecure_port(self.cfg.listen)
        if not self.port:
            raise RuntimeError(f"could not bind {self.cfg.listen} (is another listener on that exact address?)")
        self.server.start()
        log.info("listening on %s -> port %d (%s)", self.cfg.listen, self.port,
                 "TLS" if self.cfg.tls else "plaintext")
        return self.port

    def stop(self, grace: float = 1.0) -> None:
        self.server.stop(grace)
        if self.upstream:
            self.upstream.close()
        log.info("stopped")

    def wait(self) -> None:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
