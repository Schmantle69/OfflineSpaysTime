"""Raw-bytes proxy for every descriptor-set method the emulator does not answer itself."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import grpc

from .descriptors import MethodInfo
from .state import Stats

log = logging.getLogger("scos.proxy")

_DROP_PREFIXES = (":", "grpc-")
_DROP_KEYS = {"te", "content-type", "user-agent", "content-length", "host"}


def strip_metadata(md) -> list[tuple[str, str | bytes]]:
    out = []
    for k, v in md or ():
        lk = k.lower()
        if lk in _DROP_KEYS or lk.startswith(_DROP_PREFIXES):
            continue
        out.append((k, v))
    return out


class Upstream:
    def __init__(self, target: str, *, plaintext: bool = False, root_pem: str | Path | None = None,
                 authority: str | None = None):
        self.target = target
        self.plaintext = plaintext
        self.root_pem = Path(root_pem).read_bytes() if root_pem else None
        self.authority = authority
        self._lock = threading.Lock()
        self._channel: grpc.Channel | None = None

    @property
    def channel(self) -> grpc.Channel:
        with self._lock:
            if self._channel is None:
                opts = [("grpc.max_receive_message_length", 64 * 1024 * 1024),
                        ("grpc.max_send_message_length", 64 * 1024 * 1024),
                        ("grpc.keepalive_time_ms", 30000)]
                if self.plaintext:
                    self._channel = grpc.insecure_channel(self.target, options=opts)
                else:
                    if self.authority:
                        opts.append(("grpc.ssl_target_name_override", self.authority))
                    creds = grpc.ssl_channel_credentials(root_certificates=self.root_pem)
                    self._channel = grpc.secure_channel(self.target, creds, options=opts)
                log.info("upstream channel -> %s (%s)", self.target,
                         "plaintext" if self.plaintext else f"tls, authority={self.authority or 'default'}")
            return self._channel

    def close(self) -> None:
        with self._lock:
            if self._channel is not None:
                self._channel.close()
                self._channel = None


def make_passthrough(method: MethodInfo, upstream: Upstream, stats: Stats) -> grpc.RpcMethodHandler:
    identity = lambda b: b  # noqa: E731  bytes in, bytes out; the schema is the client's business
    path = method.path

    def _abort(context, err: grpc.RpcError):
        code = err.code() if hasattr(err, "code") else grpc.StatusCode.UNAVAILABLE
        details = err.details() if hasattr(err, "details") else str(err)
        log.info("proxy %s <- %s: %s", path, code.name, details)
        stats.record(path, "proxy", code.name)
        context.abort(code, details or "")

    def _finish(context, call, t0: float, note: str = "OK"):
        try:
            context.set_trailing_metadata(strip_metadata(call.trailing_metadata()))
        except Exception:
            pass
        ms = (time.perf_counter() - t0) * 1000
        log.info("proxy %s <- %s (%.1f ms)", path, note, ms)
        stats.record(path, "proxy", note, ms)

    def _timeout(context):
        t = context.time_remaining()
        return None if t is None or t <= 0 else t

    def unary_unary(request, context):
        t0 = time.perf_counter()
        md = strip_metadata(context.invocation_metadata())
        log.info("proxy %s -> upstream (%d bytes)", path, len(request))
        try:
            resp, call = upstream.channel.unary_unary(path).with_call(request, metadata=md, timeout=_timeout(context))
        except grpc.RpcError as e:
            _abort(context, e)
            return b""
        _finish(context, call, t0)
        return resp

    def unary_stream(request, context):
        t0 = time.perf_counter()
        md = strip_metadata(context.invocation_metadata())
        log.info("proxy %s -> upstream stream (%d bytes)", path, len(request))
        n = 0
        try:
            call = upstream.channel.unary_stream(path)(request, metadata=md, timeout=_timeout(context))
            for chunk in call:
                n += 1
                yield chunk
        except grpc.RpcError as e:
            _abort(context, e)
            return
        _finish(context, call, t0, f"{n} msg")

    def stream_unary(request_iterator, context):
        t0 = time.perf_counter()
        md = strip_metadata(context.invocation_metadata())
        log.info("proxy %s -> upstream (client stream)", path)
        try:
            resp, call = upstream.channel.stream_unary(path).with_call(request_iterator, metadata=md,
                                                                      timeout=_timeout(context))
        except grpc.RpcError as e:
            _abort(context, e)
            return b""
        _finish(context, call, t0)
        return resp

    def stream_stream(request_iterator, context):
        t0 = time.perf_counter()
        md = strip_metadata(context.invocation_metadata())
        log.info("proxy %s -> upstream (bidi stream)", path)
        n = 0
        try:
            call = upstream.channel.stream_stream(path)(request_iterator, metadata=md, timeout=_timeout(context))
            for chunk in call:
                n += 1
                yield chunk
        except grpc.RpcError as e:
            _abort(context, e)
            return
        _finish(context, call, t0, f"{n} msg")

    kw = dict(request_deserializer=identity, response_serializer=identity)
    return {
        "unary_unary": lambda: grpc.unary_unary_rpc_method_handler(unary_unary, **kw),
        "unary_stream": lambda: grpc.unary_stream_rpc_method_handler(unary_stream, **kw),
        "stream_unary": lambda: grpc.stream_unary_rpc_method_handler(stream_unary, **kw),
        "stream_stream": lambda: grpc.stream_stream_rpc_method_handler(stream_stream, **kw),
    }[method.kind]()
