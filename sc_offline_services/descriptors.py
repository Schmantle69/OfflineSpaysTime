"""Load a FileDescriptorSet and hand out message classes and method metadata.

Works on the reconstructed set built from ./protos and on the real set the rig
extracted from the client (sc_client_descriptors.pb); the server never imports
generated *_pb2 modules.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

log = logging.getLogger("scos.descriptors")


@dataclass(frozen=True)
class MethodInfo:
    path: str  # "/package.Service/Method", as it appears on the wire
    service: str  # full service name
    name: str
    input_type: str  # full message name
    output_type: str
    client_streaming: bool
    server_streaming: bool

    @property
    def kind(self) -> str:
        if self.client_streaming and self.server_streaming:
            return "stream_stream"
        if self.client_streaming:
            return "stream_unary"
        if self.server_streaming:
            return "unary_stream"
        return "unary_unary"


def _dependency_order(files: Iterable[descriptor_pb2.FileDescriptorProto]) -> list[descriptor_pb2.FileDescriptorProto]:
    """Topologically order files so every import is added to the pool before its user.

    protoc emits sets in order already; a set decoded out of an executable need not be.
    """
    files = list(files)
    by_name = {f.name: f for f in files}
    seen: set[str] = set()
    order: list[descriptor_pb2.FileDescriptorProto] = []

    def visit(f: descriptor_pb2.FileDescriptorProto) -> None:
        if f.name in seen:
            return
        seen.add(f.name)
        for dep in f.dependency:
            d = by_name.get(dep)
            if d is not None:
                visit(d)
        order.append(f)

    for f in files:
        visit(f)
    return order


class DescriptorSet:
    def __init__(self, fds: descriptor_pb2.FileDescriptorSet):
        self.fds = fds
        self.pool = descriptor_pool.DescriptorPool()
        self.files: list[str] = []
        self.methods: dict[str, MethodInfo] = {}
        self._classes: dict[str, type] = {}
        for fd in _dependency_order(fds.file):
            try:
                self.pool.FindFileByName(fd.name)
                log.debug("descriptor file %s already present, skipped", fd.name)
                continue
            except KeyError:
                pass
            self.pool.AddSerializedFile(fd.SerializeToString())
            self.files.append(fd.name)
            for svc in fd.service:
                svc_full = f"{fd.package}.{svc.name}" if fd.package else svc.name
                for m in svc.method:
                    path = f"/{svc_full}/{m.name}"
                    self.methods[path] = MethodInfo(
                        path=path,
                        service=svc_full,
                        name=m.name,
                        input_type=m.input_type.lstrip("."),
                        output_type=m.output_type.lstrip("."),
                        client_streaming=bool(m.client_streaming),
                        server_streaming=bool(m.server_streaming),
                    )
        log.info("descriptor set: %d files, %d services, %d methods",
                 len(self.files), len(self.services()), len(self.methods))

    @classmethod
    def load(cls, path: str | Path) -> "DescriptorSet":
        fds = descriptor_pb2.FileDescriptorSet()
        fds.ParseFromString(Path(path).read_bytes())
        return cls(fds)

    # ---- lookups -------------------------------------------------------------------------

    def services(self) -> list[str]:
        return sorted({m.service for m in self.methods.values()})

    def has_service(self, full_name: str) -> bool:
        return any(m.service == full_name for m in self.methods.values())

    def service_methods(self, full_name: str) -> list[MethodInfo]:
        return [m for m in self.methods.values() if m.service == full_name]

    def has_message(self, full_name: str) -> bool:
        try:
            self.pool.FindMessageTypeByName(full_name)
            return True
        except KeyError:
            return False

    def message_class(self, full_name: str) -> type:
        cls = self._classes.get(full_name)
        if cls is None:
            cls = message_factory.GetMessageClass(self.pool.FindMessageTypeByName(full_name))
            self._classes[full_name] = cls
        return cls

    def new(self, full_name: str, **fields):
        return self.message_class(full_name)(**fields)

    def resolve_message_name(self, name: str, default_package: str | None = None) -> str:
        """Accept a full name or a bare message name inside default_package."""
        if self.has_message(name):
            return name
        if default_package and self.has_message(f"{default_package}.{name}"):
            return f"{default_package}.{name}"
        raise KeyError(f"no message type {name!r} in the descriptor set")

    # ---- json ----------------------------------------------------------------------------

    def parse_dict(self, full_name: str, data: dict, ignore_unknown: bool = True):
        msg = self.message_class(full_name)()
        json_format.ParseDict(data, msg, ignore_unknown_fields=ignore_unknown, descriptor_pool=self.pool)
        return msg

    def to_dict(self, msg) -> dict:
        return json_format.MessageToDict(msg, preserving_proto_field_name=True, descriptor_pool=self.pool)
