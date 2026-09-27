IM = "sc.external.services.instance_manager.v1"


def _get(rig, shard):
    req = rig.ds.new(f"{IM}.GetAvailableInstancesRequest")
    req.shard_id = shard
    req.instance_prerequisites["personal_hangar"].SetInParent()
    return rig.unary(f"/{IM}.InstanceManagerService/GetAvailableInstances", req)


def test_wildcard_instance_echoes_requested_shard(rig):
    resp = _get(rig, "local_shard")
    assert len(resp.instance_results) == 1
    info = resp.instance_results[0]
    assert info.eligible
    assert info.instance_identifier == "personal_hangar:offline:1"
    inst = info.instance
    assert inst.shard_id == "local_shard"
    assert inst.status == 7  # STOWED
    assert inst.template.type == 1  # PLAYER_HANGAR
    assert inst.template.instance_oc_path.endswith("hangar_smltop_001.socpak")
    assert inst.template.config.cleanup_strategy == 2  # STOW
    assert inst.stow_inventory_id == "inv-1"
    assert inst.WhichOneof("stow_inventory") == "stow_inventory_id"


def test_fixed_shard_instance_only_for_its_shard(rig):
    resp = _get(rig, "other_shard")
    ids = sorted(i.instance_identifier for i in resp.instance_results)
    assert ids == ["elsewhere", "personal_hangar:offline:1"]


def test_wire_roundtrip_of_served_instance(rig):
    """What the client parses is the bytes; make sure a re-parse from bytes matches."""
    resp = _get(rig, "local_shard")
    Resp = rig.ds.message_class(f"{IM}.GetAvailableInstancesResponse")
    again = Resp.FromString(resp.SerializeToString())
    assert again == resp
