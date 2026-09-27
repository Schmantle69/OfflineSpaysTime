import json
import threading
import urllib.request

from sc_offline_services.admin import AdminServer

PUSH = "sc.external.services.push.v1"
IM = "sc.external.services.instance_manager.v1"


def _listen(rig):
    req = rig.ds.new(f"{PUSH}.ListenRequest")
    return rig.server_stream(f"/{PUSH}.PushService/Listen", req, timeout=20)


def _unpack(rig, listen_response):
    assert len(listen_response.envelopes) == 1
    msgs = listen_response.envelopes[0].messages
    assert len(msgs) == 1 and msgs[0].WhichOneof("payload") == "any"
    any_msg = msgs[0].any
    full = any_msg.type_url.split("/", 1)[1]
    return full, rig.ds.message_class(full).FromString(any_msg.value)


def test_publish_reaches_open_listen_stream(rig):
    call = _listen(rig)
    # wait until the subscriber is registered
    for _ in range(100):
        if rig.emu.hub.subscriber_count() == 1:
            break
        threading.Event().wait(0.02)
    n = rig.emu.hub.publish("StartUnstowingInstance", {
        "instance": {"instance_id": "id-1", "shard_id": "local_shard", "status": 8},
        "inventory_id": "inv-1",
        "shard_destination": {"shard_id": "local_shard"},
        "command_id": "cmd-1",
    })
    assert n == 1
    full, msg = _unpack(rig, next(call))
    assert full == f"{IM}.StartUnstowingInstance"
    assert msg.inventory_id == "inv-1" and msg.instance.status == 8 and msg.command_id == "cmd-1"
    assert msg.shard_destination.shard_id == "local_shard"
    call.cancel()
    for _ in range(100):
        if rig.emu.hub.subscriber_count() == 0:
            break
        threading.Event().wait(0.05)
    assert rig.emu.hub.subscriber_count() == 0


def test_push_on_listen_fixture_is_delivered_first(rig):
    rig.fixtures.replace({**json.loads(rig.fixtures.path.read_text()),
                          "push_on_listen": [{"type": "InstanceBecameActive",
                                              "message": {"instance": {"instance_id": "boot"}}}]})
    call = _listen(rig)
    full, msg = _unpack(rig, next(call))
    assert full.endswith("InstanceBecameActive") and msg.instance.instance_id == "boot"
    call.cancel()


def test_admin_push_status_log_reload(rig):
    admin = AdminServer("127.0.0.1", 0, hub=rig.emu.hub, fixtures=rig.fixtures, stats=rig.emu.stats)
    admin.start()
    host, port = admin.address
    base = f"http://{host}:{port}"
    try:
        call = _listen(rig)
        for _ in range(100):
            if rig.emu.hub.subscriber_count() == 1:
                break
            threading.Event().wait(0.02)
        body = json.dumps({"type": "PlayerJoinedInstance",
                           "message": {"instance": {"instance_id": "id-1"}, "player_geid": 42}}).encode()
        r = urllib.request.urlopen(urllib.request.Request(f"{base}/push", data=body,
                                                          headers={"Content-Type": "application/json"}))
        assert json.load(r)["delivered_to"] == 1
        full, msg = _unpack(rig, next(call))
        assert full.endswith("PlayerJoinedInstance") and msg.player_geid == 42
        call.cancel()

        # bad type is a 400, not a crash
        bad = json.dumps({"type": "NoSuchMessage", "message": {}}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(f"{base}/push", data=bad,
                                                          headers={"Content-Type": "application/json"}))
            assert False, "expected 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400

        status = json.load(urllib.request.urlopen(f"{base}/status"))
        assert status["push_published"] >= 1 and "grpc/endpoints" in status["config_keys"]
        assert status["counters"].get("rpc.local", 0) >= 1

        gen_before = rig.fixtures.generation
        r = json.load(urllib.request.urlopen(urllib.request.Request(f"{base}/reload", data=b"", method="POST")))
        assert r["generation"] == gen_before + 1

        text = urllib.request.urlopen(f"{base}/log?n=5").read().decode()
        assert isinstance(text, str)
    finally:
        admin.stop()
