import grpc

ECHO = "test.echo.EchoService"


def test_unary_is_forwarded_with_metadata_both_ways(rig):
    req = rig.ds.new("test.echo.EchoRequest", text="hi")
    Resp = rig.ds.message_class("test.echo.EchoResponse")
    call = rig.channel.unary_unary(f"/{ECHO}/Echo", request_serializer=req.SerializeToString,
                                   response_deserializer=Resp.FromString)
    resp, info = call.with_call(req, metadata=(("x-test", "abc"),), timeout=10)
    assert resp.text == "echo:hi"
    assert resp.header == "abc"  # request metadata reached the upstream
    assert dict(info.trailing_metadata()).get("x-upstream") == "seen"  # upstream trailers came back


def test_upstream_error_status_is_propagated(rig):
    req = rig.ds.new("test.echo.EchoRequest", text="x")
    try:
        rig.unary(f"/{ECHO}/Fail", req)
        assert False, "expected NOT_FOUND"
    except grpc.RpcError as e:
        assert e.code() == grpc.StatusCode.NOT_FOUND
        assert e.details() == "nope: x"


def test_server_stream_is_forwarded(rig):
    req = rig.ds.new("test.echo.EchoRequest", text="s")
    texts = [r.text for r in rig.server_stream(f"/{ECHO}/Stream", req)]
    assert texts == ["s#0", "s#1", "s#2"]


def test_client_stream_is_forwarded(rig):
    Req = rig.ds.message_class("test.echo.EchoRequest")
    resp = rig.client_stream(f"/{ECHO}/Collect", [Req(text="a"), Req(text="b"), Req(text="c")])
    assert resp.text == "a+b+c"


def test_unknown_method_is_unimplemented_and_counted(rig):
    req = rig.ds.new("test.echo.EchoRequest", text="?")
    call = rig.channel.unary_unary("/no.such.Service/Method", request_serializer=req.SerializeToString,
                                   response_deserializer=lambda b: b)
    try:
        call(req, timeout=5)
        assert False, "expected UNIMPLEMENTED"
    except grpc.RpcError as e:
        assert e.code() == grpc.StatusCode.UNIMPLEMENTED
    assert rig.emu.stats.snapshot()["counters"].get("rpc.unknown") == 1


def test_local_routes_win_over_passthrough(rig):
    """ConfigService is in the set and would be proxied, but the local handler must answer."""
    assert rig.emu.stats.snapshot()["counters"].get("rpc.proxy", 0) == 0
    req = rig.ds.new("sc.external.services.configuration.v1.QueryConfigRequest")
    req.query.config_group, req.query.config_key = "plain", "string"
    assert rig.unary("/sc.external.services.configuration.v1.ConfigService/QueryConfig", req).response.value == "just text"
    assert rig.emu.stats.snapshot()["counters"].get("rpc.proxy", 0) == 0
