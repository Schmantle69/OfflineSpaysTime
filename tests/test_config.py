import json
import threading
import time

import grpc

CFG = "sc.external.services.configuration.v1"
FOUND, FOUND_NO_UPDATE, NOT_FOUND = 1, 2, 3


def _query(rig, group, key, curr_version=0):
    req = rig.ds.new(f"{CFG}.QueryConfigRequest")
    req.query.config_group = group
    req.query.config_key = key
    req.query.curr_version = curr_version
    return rig.unary(f"/{CFG}.ConfigService/QueryConfig", req).response


def test_query_found_object_value_is_json(rig):
    r = _query(rig, "grpc", "endpoints")
    assert r.result == FOUND
    assert r.config_group == "grpc" and r.config_key == "endpoints"
    assert r.version == 3
    assert json.loads(r.value) == {"endpoints": {"instance_manager": "127.0.0.1:443"}}


def test_query_found_string_value_verbatim(rig):
    r = _query(rig, "plain", "string")
    assert r.result == FOUND and r.value == "just text" and r.version == 1


def test_query_null_entry_and_unknown_are_not_found(rig):
    assert _query(rig, "cvars", "variables").result == NOT_FOUND
    r = _query(rig, "nothing", "here")
    assert r.result == NOT_FOUND and r.config_group == "nothing" and r.config_key == "here" and r.value == ""


def test_query_disabled_entry_is_not_found(rig):
    assert _query(rig, "services", "instance_manager_external").result == NOT_FOUND


def test_query_same_version_is_found_no_update(rig):
    r = _query(rig, "grpc", "endpoints", curr_version=3)
    assert r.result == FOUND_NO_UPDATE and r.value == ""


def test_watch_multi_answers_each_pair_then_follows_reload(rig):
    req = rig.ds.new(f"{CFG}.WatchMultiConfigurationsRequest")
    for g, k in (("grpc", "endpoints"), ("cvars", "variables")):
        p = req.request.group_key_pairs.add()
        p.config_group, p.config_key = g, k
    call = rig.server_stream(f"/{CFG}.ConfigService/WatchMultiConfigurations", req, timeout=15)
    first = next(call).response
    second = next(call).response
    assert (first.config_key, first.result) == ("endpoints", FOUND)
    assert (second.config_key, second.result) == ("variables", NOT_FOUND)

    # a reload flips cvars/variables to FOUND and the open stream re-sends both keys
    data = json.loads(rig.fixtures.path.read_text())
    data["config"]["cvars/variables"] = {"version": 9, "value": "now-found"}
    rig.fixtures.path.write_text(json.dumps(data))
    threading.Timer(0.2, rig.fixtures.reload).start()
    got = {}
    t0 = time.time()
    while len(got) < 2 and time.time() - t0 < 10:
        r = next(call).response
        got[r.config_key] = r
    assert got["variables"].result == FOUND and got["variables"].value == "now-found" and got["variables"].version == 9
    assert got["endpoints"].result == FOUND
    call.cancel()


def test_watch_config_single_key_stream_can_be_cancelled(rig):
    req = rig.ds.new(f"{CFG}.WatchConfigRequest")
    req.query.config_group, req.query.config_key = "plain", "string"
    call = rig.server_stream(f"/{CFG}.ConfigService/WatchConfig", req, timeout=15)
    assert next(call).response.value == "just text"
    call.cancel()
    try:
        next(call)
    except grpc.RpcError as e:
        assert e.code() == grpc.StatusCode.CANCELLED
