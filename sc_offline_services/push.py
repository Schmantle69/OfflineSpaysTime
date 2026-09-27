"""PushService fan-out: anything published here reaches every open Listen stream."""
from __future__ import annotations

import logging
import queue
import threading

from .descriptors import DescriptorSet

log = logging.getLogger("scos.push")

# Wire names ASSUMED from the measured shape ListenResponse{envelopes[]{messages[]{control|any}}}.
# If the real descriptor set names them differently, this is the one place to change.
LISTEN_RESPONSE = "sc.external.services.push.v1.ListenResponse"
FIELD_ENVELOPES = "envelopes"
FIELD_MESSAGES = "messages"
FIELD_ANY = "any"
INSTANCE_MANAGER_PACKAGE = "sc.external.services.instance_manager.v1"
ANY_PREFIX = "type.googleapis.com/"


class PushHub:
    def __init__(self, ds: DescriptorSet):
        self.ds = ds
        self._lock = threading.Lock()
        self._subs: dict[int, queue.Queue] = {}
        self._next = 1
        self.published = 0

    # ---- subscriptions ------------------------------------------------------------------

    def subscribe(self) -> tuple[int, queue.Queue]:
        with self._lock:
            sid = self._next
            self._next += 1
            q: queue.Queue = queue.Queue()
            self._subs[sid] = q
        return sid, q

    def unsubscribe(self, sid: int) -> None:
        with self._lock:
            self._subs.pop(sid, None)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    # ---- building ------------------------------------------------------------------------

    def build_any(self, type_name: str, payload):
        full = self.ds.resolve_message_name(type_name, INSTANCE_MANAGER_PACKAGE)
        msg = payload if not isinstance(payload, dict) else self.ds.parse_dict(full, payload)
        any_msg = self.ds.new("google.protobuf.Any")
        any_msg.type_url = ANY_PREFIX + full
        any_msg.value = msg.SerializeToString()
        return any_msg

    def build_listen_response(self, any_msgs: list):
        resp = self.ds.new(LISTEN_RESPONSE)
        env = getattr(resp, FIELD_ENVELOPES).add()
        for a in any_msgs:
            m = getattr(env, FIELD_MESSAGES).add()
            getattr(m, FIELD_ANY).CopyFrom(a)
        return resp

    # ---- publishing ----------------------------------------------------------------------

    def publish(self, type_name: str, payload, only: int | None = None) -> int:
        """Queue one message for every subscriber (or one). Returns subscribers reached."""
        resp = self.build_listen_response([self.build_any(type_name, payload)])
        with self._lock:
            targets = [self._subs[only]] if only is not None and only in self._subs else (
                [] if only is not None else list(self._subs.values()))
        for q in targets:
            q.put(resp)
        self.published += 1
        log.info("push %s -> %d subscriber(s)", type_name, len(targets))
        return len(targets)
