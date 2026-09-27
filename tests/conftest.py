from __future__ import annotations

import json
import sys
from concurrent import futures
from pathlib import Path

import grpc
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_descriptor_set import build  # noqa: E402
from sc_offline_services import DescriptorSet, Emulator, Fixtures, ServerConfig  # noqa: E402

ECHO = "test.echo.EchoService"

FIXTURE = {
    "config": {
        "cvars/variables": None,
        "grpc/endpoints": {"version": 3, "value": {"endpoints": {"instance_manager": "127.0.0.1:443"}}},
        "services/instance_manager_external": {"disabled": True, "value": {}},
        "plain/string": "just text",
    },
    "instances": [
        {
            "instance_id": "id-1",
            "instance_identifier": "personal_hangar:offline:1",
            "shard_id": "*",
            "status": 7,
            "template": {"instance_oc_path": "objectcontainers/pu/loc/mod/common/hangar/util_a/hangar_smltop_001.socpak",
                         "type": 1, "config": {"cleanup_strategy": 2}},
            "stow_inventory_id": "inv-1",
        },
        {
            "instance_id": "id-2",
            "instance_identifier": "elsewhere",
            "shard_id": "other_shard",
            "status": 7,
            "template": {"instance_oc_path": "x.socpak", "type": 1},
        },
    ],
    "push_on_listen": [],
}


@pytest.fixture(scope="session")
def descriptor_path(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("desc") / "test_descriptors.pb"
    return build(out, [ROOT / "protos", ROOT / "tests" / "protos"])


@pytest.fixture(scope="session")
def ds(descriptor_path) -> DescriptorSet:
    return DescriptorSet.load(descriptor_path)


@pytest.fixture(scope="session")
def upstream(ds):
    """A plaintext EchoService standing in for StarBackend."""
    Req = ds.message_class("test.echo.EchoRequest")
    Resp = ds.message_class("test.echo.EchoResponse")

    def echo(req, ctx):
        md = dict(ctx.invocation_metadata())
        ctx.set_trailing_metadata((("x-upstream", "seen"),))
        return Resp(text="echo:" + req.text, header=md.get("x-test", ""))

    def fail(req, ctx):
        ctx.abort(grpc.StatusCode.NOT_FOUND, "nope: " + req.text)

    def stream(req, ctx):
        for i in range(3):
            yield Resp(text=f"{req.text}#{i}")

    def collect(req_iter, ctx):
        return Resp(text="+".join(r.text for r in req_iter))

    routes = {
        f"/{ECHO}/Echo": grpc.unary_unary_rpc_method_handler(echo, Req.FromString, Resp.SerializeToString),
        f"/{ECHO}/Fail": grpc.unary_unary_rpc_method_handler(fail, Req.FromString, Resp.SerializeToString),
        f"/{ECHO}/Stream": grpc.unary_stream_rpc_method_handler(stream, Req.FromString, Resp.SerializeToString),
        f"/{ECHO}/Collect": grpc.stream_unary_rpc_method_handler(collect, Req.FromString, Resp.SerializeToString),
    }

    class H(grpc.GenericRpcHandler):
        def service(self, d):
            return routes.get(d.method)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4), handlers=[H()])
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield f"127.0.0.1:{port}"
    server.stop(0)


class Rig:
    def __init__(self, emu: Emulator, fixtures: Fixtures, ds: DescriptorSet):
        self.emu, self.fixtures, self.ds = emu, fixtures, ds
        self.target = f"127.0.0.1:{emu.port}"
        self.channel = grpc.insecure_channel(self.target)

    def unary(self, path: str, req, metadata=None):
        m = self.ds.methods[path]
        Resp = self.ds.message_class(m.output_type)
        return self.channel.unary_unary(path, request_serializer=req.SerializeToString,
                                        response_deserializer=Resp.FromString)(req, metadata=metadata, timeout=10)

    def server_stream(self, path: str, req, metadata=None, timeout=10):
        m = self.ds.methods[path]
        Resp = self.ds.message_class(m.output_type)
        return self.channel.unary_stream(path, request_serializer=req.SerializeToString,
                                         response_deserializer=Resp.FromString)(req, metadata=metadata, timeout=timeout)

    def client_stream(self, path: str, reqs):
        m = self.ds.methods[path]
        Req = self.ds.message_class(m.input_type)
        Resp = self.ds.message_class(m.output_type)
        return self.channel.stream_unary(path, request_serializer=Req.SerializeToString,
                                         response_deserializer=Resp.FromString)(iter(reqs), timeout=10)

    def close(self):
        self.channel.close()
        self.emu.stop(0)


@pytest.fixture
def rig(ds, upstream, tmp_path) -> Rig:
    fixture_file = tmp_path / "fixtures.json"
    fixture_file.write_text(json.dumps(FIXTURE), encoding="utf-8")
    fixtures = Fixtures(fixture_file)
    cfg = ServerConfig(listen="127.0.0.1:0", upstream=upstream, upstream_plaintext=True, upstream_authority=None)
    emu = Emulator(ds, fixtures, cfg)
    emu.start()
    r = Rig(emu, fixtures, ds)
    yield r
    r.close()
