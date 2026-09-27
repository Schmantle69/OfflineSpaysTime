from google.protobuf import descriptor_pb2

from sc_offline_services import DescriptorSet


def test_services_and_methods_present(ds):
    assert ds.has_service("sc.external.services.configuration.v1.ConfigService")
    assert ds.has_service("sc.external.services.instance_manager.v1.InstanceManagerService")
    assert ds.has_service("sc.external.services.push.v1.PushService")
    m = ds.methods["/sc.external.services.push.v1.PushService/Listen"]
    assert m.server_streaming and not m.client_streaming and m.kind == "unary_stream"
    q = ds.methods["/sc.external.services.configuration.v1.ConfigService/QueryConfig"]
    assert q.input_type == "sc.external.services.configuration.v1.QueryConfigRequest"


def test_measured_field_numbers(ds):
    """The numbers the records measured must survive any edit of the protos."""
    cq = ds.pool.FindMessageTypeByName("sc.external.services.configuration.v1.ConfigQuery")
    assert {f.name: f.number for f in cq.fields} == {
        "config_group": 1, "config_key": 2, "curr_node": 3, "curr_version": 4, "matchers": 5}
    cr = ds.pool.FindMessageTypeByName("sc.external.services.configuration.v1.ConfigResponse")
    assert {f.name: f.number for f in cr.fields} == {
        "result": 1, "curr_node": 2, "config_group": 3, "config_key": 4, "value": 5, "version": 6}
    inst = ds.pool.FindMessageTypeByName("sc.external.services.instance_manager.v1.Instance")
    nums = {f.name: f.number for f in inst.fields}
    assert nums["instance_id"] == 1 and nums["template"] == 6 and nums["status"] == 7
    assert nums["stow_inventory_id"] == 10 and nums["completed_at"] == 12
    st = ds.pool.FindEnumTypeByName("sc.external.services.instance_manager.v1.InstanceStatus")
    assert st.values_by_name["STOWED"].number == 7
    ty = ds.pool.FindEnumTypeByName("sc.external.services.instance_manager.v1.InstanceType")
    assert ty.values_by_name["PLAYER_HANGAR"].number == 1


def test_out_of_order_set_loads(descriptor_path):
    """A set decoded from an executable need not be topologically ordered."""
    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(descriptor_path.read_bytes())
    reversed_set = descriptor_pb2.FileDescriptorSet()
    for f in reversed(list(fds.file)):
        reversed_set.file.add().CopyFrom(f)
    ds2 = DescriptorSet(reversed_set)
    assert len(ds2.methods) == len(DescriptorSet(fds).methods)
    assert ds2.has_message("sc.external.services.instance_manager.v1.StartUnstowingInstance")


def test_resolve_short_names(ds):
    assert ds.resolve_message_name("StartUnstowingInstance", "sc.external.services.instance_manager.v1") \
        == "sc.external.services.instance_manager.v1.StartUnstowingInstance"
