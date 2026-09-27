import sys
from pathlib import Path

import grpc

from sc_offline_services import Emulator, Fixtures, ServerConfig

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from make_tls import generate  # noqa: E402

CFG = "sc.external.services.configuration.v1"


def test_tls_seat_with_generated_ca(ds, tmp_path):
    paths = generate(tmp_path / "tls", [], days=30)
    fixtures = Fixtures(data={"config": {"plain/string": "over-tls"}})
    cfg = ServerConfig(listen="127.0.0.1:0", tls_cert=paths["leaf.pem"], tls_key=paths["leaf.key"], upstream=None)
    emu = Emulator(ds, fixtures, cfg)
    port = emu.start()
    try:
        creds = grpc.ssl_channel_credentials(root_certificates=paths["ca.pem"].read_bytes())
        # the leaf carries SAN IP 127.0.0.1, so no name override is needed; the client verifies the IP
        ch = grpc.secure_channel(f"127.0.0.1:{port}", creds)
        req = ds.new(f"{CFG}.QueryConfigRequest")
        req.query.config_group, req.query.config_key = "plain", "string"
        Resp = ds.message_class(f"{CFG}.QueryConfigResponse")
        resp = ch.unary_unary(f"/{CFG}.ConfigService/QueryConfig", request_serializer=req.SerializeToString,
                              response_deserializer=Resp.FromString)(req, timeout=10)
        assert resp.response.value == "over-tls"
        ch.close()
    finally:
        emu.stop(0)


def test_untrusted_client_is_refused(ds, tmp_path):
    paths = generate(tmp_path / "tls", [], days=30)
    other = generate(tmp_path / "other", [], days=30)
    fixtures = Fixtures(data={"config": {}})
    cfg = ServerConfig(listen="127.0.0.1:0", tls_cert=paths["leaf.pem"], tls_key=paths["leaf.key"], upstream=None)
    emu = Emulator(ds, fixtures, cfg)
    port = emu.start()
    try:
        creds = grpc.ssl_channel_credentials(root_certificates=other["ca.pem"].read_bytes())
        ch = grpc.secure_channel(f"127.0.0.1:{port}", creds)
        req = ds.new(f"{CFG}.QueryConfigRequest")
        try:
            ch.unary_unary(f"/{CFG}.ConfigService/QueryConfig", request_serializer=req.SerializeToString,
                           response_deserializer=lambda b: b)(req, timeout=5)
            assert False, "a client trusting a different CA must not connect"
        except grpc.RpcError as e:
            assert e.code() == grpc.StatusCode.UNAVAILABLE
        ch.close()
    finally:
        emu.stop(0)
