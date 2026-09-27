"""Local handlers for the three services on the hangar seam, built on the descriptor set."""
from __future__ import annotations

import logging
import queue
import threading
import time

import grpc

from .descriptors import DescriptorSet, MethodInfo
from .fixtures import Fixtures
from .push import PushHub
from .state import Stats

log = logging.getLogger("scos.local")

CONFIG_SERVICE = "sc.external.services.configuration.v1.ConfigService"
INSTANCE_MANAGER_SERVICE = "sc.external.services.instance_manager.v1.InstanceManagerService"
PUSH_SERVICE = "sc.external.services.push.v1.PushService"

# Measured enum values (ConfigResponse.result).
CONFIG_FOUND = 1
CONFIG_FOUND_NO_UPDATE = 2
CONFIG_NOT_FOUND = 3
CONFIG_RESULT_NAMES = {1: "FOUND", 2: "FOUND_NO_UPDATE", 3: "NOT_FOUND"}

# Wrapper field names measured ("query", "response", "request", "group_key_pairs").
F_QUERY = "query"
F_RESPONSE = "response"
F_REQUEST = "request"
F_GROUP_KEY_PAIRS = "group_key_pairs"

INSTANCE_TYPE = "sc.external.services.instance_manager.v1.Instance"


def method_handler(method: MethodInfo, ds: DescriptorSet, behaviour) -> grpc.RpcMethodHandler:
    req_cls = ds.message_class(method.input_type)
    resp_cls = ds.message_class(method.output_type)
    kw = dict(request_deserializer=req_cls.FromString, response_serializer=resp_cls.SerializeToString)
    return {
        "unary_unary": grpc.unary_unary_rpc_method_handler,
        "unary_stream": grpc.unary_stream_rpc_method_handler,
        "stream_unary": grpc.stream_unary_rpc_method_handler,
        "stream_stream": grpc.stream_stream_rpc_method_handler,
    }[method.kind](behaviour, **kw)


def _peer(context) -> str:
    try:
        return context.peer()
    except Exception:
        return "?"


def _until_cancelled(context) -> threading.Event:
    done = threading.Event()
    context.add_callback(done.set)
    return done


class ConfigHandlers:
    def __init__(self, ds: DescriptorSet, fixtures: Fixtures, stats: Stats):
        self.ds, self.fixtures, self.stats = ds, fixtures, stats

    def _fill(self, resp, group: str, key: str, curr_version: int) -> str:
        resp.config_group = group
        resp.config_key = key
        hit = self.fixtures.config_lookup(group, key)
        if hit is None:
            resp.result = CONFIG_NOT_FOUND
        else:
            value, version = hit
            resp.version = version
            if curr_version and curr_version == version:
                resp.result = CONFIG_FOUND_NO_UPDATE
            else:
                resp.result = CONFIG_FOUND
                resp.value = value
        return CONFIG_RESULT_NAMES[resp.result]

    def query_config(self, request, context):
        q = getattr(request, F_QUERY)
        resp = self.ds.new(f"{CONFIG_SERVICE.rsplit('.', 1)[0]}.QueryConfigResponse")
        outcome = self._fill(getattr(resp, F_RESPONSE), q.config_group, q.config_key, q.curr_version)
        log.info("ConfigService.QueryConfig %s/%s (curr_version=%d) -> %s",
                 q.config_group, q.config_key, q.curr_version, outcome)
        self.stats.record("ConfigService.QueryConfig", "local", f"{q.config_group}/{q.config_key}={outcome}")
        return resp

    def _follow(self, context, pairs, resp_type: str):
        """After the initial answers, re-send the keys whenever the fixtures reload."""
        done = _until_cancelled(context)
        gen = self.fixtures.generation
        while not done.is_set() and context.is_active():
            with self.fixtures.cond:
                self.fixtures.cond.wait_for(lambda: self.fixtures.generation != gen, timeout=1.0)
                changed = self.fixtures.generation != gen
                gen = self.fixtures.generation
            if changed:
                for group, key in pairs:
                    resp = self.ds.new(resp_type)
                    outcome = self._fill(getattr(resp, F_RESPONSE), group, key, 0)
                    log.info("watch update %s/%s -> %s", group, key, outcome)
                    yield resp

    def watch_config(self, request, context):
        q = getattr(request, F_QUERY)
        pkg = CONFIG_SERVICE.rsplit(".", 1)[0]
        resp = self.ds.new(f"{pkg}.WatchConfigResponse")
        outcome = self._fill(getattr(resp, F_RESPONSE), q.config_group, q.config_key, q.curr_version)
        log.info("ConfigService.WatchConfig %s/%s -> %s (stream open)", q.config_group, q.config_key, outcome)
        self.stats.record("ConfigService.WatchConfig", "local", f"{q.config_group}/{q.config_key}={outcome}")
        yield resp
        yield from self._follow(context, [(q.config_group, q.config_key)], f"{pkg}.WatchConfigResponse")
        log.info("ConfigService.WatchConfig %s/%s stream closed", q.config_group, q.config_key)

    def watch_multi(self, request, context):
        pkg = CONFIG_SERVICE.rsplit(".", 1)[0]
        inner = getattr(request, F_REQUEST)
        pairs = [(p.config_group, p.config_key) for p in getattr(inner, F_GROUP_KEY_PAIRS)]
        log.info("ConfigService.WatchMultiConfigurations %d pair(s): %s",
                 len(pairs), ", ".join(f"{g}/{k}" for g, k in pairs))
        for group, key in pairs:
            resp = self.ds.new(f"{pkg}.WatchMultiConfigurationsResponse")
            outcome = self._fill(getattr(resp, F_RESPONSE), group, key, 0)
            log.info("  %s/%s -> %s", group, key, outcome)
            self.stats.record("ConfigService.WatchMultiConfigurations", "local", f"{group}/{key}={outcome}")
            yield resp
        yield from self._follow(context, pairs, f"{pkg}.WatchMultiConfigurationsResponse")
        log.info("ConfigService.WatchMultiConfigurations stream closed")


class InstanceManagerHandlers:
    def __init__(self, ds: DescriptorSet, fixtures: Fixtures, stats: Stats):
        self.ds, self.fixtures, self.stats = ds, fixtures, stats

    def get_available_instances(self, request, context):
        pkg = INSTANCE_MANAGER_SERVICE.rsplit(".", 1)[0]
        resp = self.ds.new(f"{pkg}.GetAvailableInstancesResponse")
        shard = request.shard_id
        prereq_keys = sorted(request.instance_prerequisites.keys())
        served = 0
        for inst in self.fixtures.instances():
            fixture_shard = inst.get("shard_id", "*")
            if fixture_shard not in ("*", "") and shard and fixture_shard != shard:
                continue
            data = dict(inst)
            if fixture_shard in ("*", ""):
                data["shard_id"] = shard
            msg = self.ds.parse_dict(INSTANCE_TYPE, data)
            info = resp.instance_results.add()
            info.instance_identifier = msg.instance_identifier
            info.instance.CopyFrom(msg)
            info.eligible = True
            served += 1
        log.info("InstanceManagerService.GetAvailableInstances shard=%r prerequisites=%s "
                 "activity_report=%s -> %d instance(s)", shard, prereq_keys,
                 request.request_activity_report, served)
        self.stats.record("InstanceManagerService.GetAvailableInstances", "local",
                          f"shard={shard} served={served}")
        return resp


class PushHandlers:
    def __init__(self, ds: DescriptorSet, fixtures: Fixtures, hub: PushHub, stats: Stats):
        self.ds, self.fixtures, self.hub, self.stats = ds, fixtures, hub, stats

    def listen(self, request, context):
        sid, q = self.hub.subscribe()
        log.info("PushService.Listen opened (subscriber %d, peer %s)", sid, _peer(context))
        self.stats.record("PushService.Listen", "local", f"open sid={sid}")
        try:
            for item in self.fixtures.push_on_listen():
                self.hub.publish(item["type"], item.get("message", {}), only=sid)
            done = _until_cancelled(context)
            while not done.is_set() and context.is_active():
                try:
                    resp = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                yield resp
        finally:
            self.hub.unsubscribe(sid)
            log.info("PushService.Listen closed (subscriber %d)", sid)


def build_local_routes(ds: DescriptorSet, fixtures: Fixtures, hub: PushHub, stats: Stats
                       ) -> dict[str, grpc.RpcMethodHandler]:
    routes: dict[str, grpc.RpcMethodHandler] = {}

    def bind(service: str, name: str, behaviour) -> None:
        path = f"/{service}/{name}"
        method = ds.methods.get(path)
        if method is None:
            log.warning("descriptor set has no %s; not served locally", path)
            return
        routes[path] = method_handler(method, ds, behaviour)

    cfg = ConfigHandlers(ds, fixtures, stats)
    bind(CONFIG_SERVICE, "QueryConfig", cfg.query_config)
    bind(CONFIG_SERVICE, "WatchConfig", cfg.watch_config)
    bind(CONFIG_SERVICE, "WatchMultiConfigurations", cfg.watch_multi)

    im = InstanceManagerHandlers(ds, fixtures, stats)
    bind(INSTANCE_MANAGER_SERVICE, "GetAvailableInstances", im.get_available_instances)

    push = PushHandlers(ds, fixtures, hub, stats)
    bind(PUSH_SERVICE, "Listen", push.listen)
    return routes
