# OfflineSpaysTime: offline services emulator for the Star Citizen client

A descriptor-driven gRPC server that sits beside a local `StarBackend.exe` and answers the
services the offline rig lacks, starting with the three on the personal-hangar seam:

| service | what the emulator does |
|---|---|
| `configuration.v1.ConfigService` | `QueryConfig`, `WatchConfig`, `WatchMultiConfigurations` from a JSON fixture |
| `instance_manager.v1.InstanceManagerService` | `GetAvailableInstances` from fixture `Instance` records |
| `push.v1.PushService` | `Listen` streams; anything posted to the admin endpoint is pushed as `google.protobuf.Any` |
| everything else in the descriptor set | proxied byte-for-byte to StarBackend, status and trailers included |

Why this exists, and where the work stands, is in `docs/RESUME_POINT_2026-09-27.md`. Short form:
the client's hangar request pump waits forever because no instance-manager service exists on the
offline rig. This server is the missing service.

## Layout

```
protos/               reconstructed .proto files (measured field numbers; ASSUMED ones are marked)
scripts/build_descriptor_set.py   protos -> build/sc_reconstructed_descriptors.pb
scripts/make_tls.py               local CA + leaf for the 127.0.0.1:443 seat
sc_offline_services/  the server (descriptors, fixtures, handlers, passthrough, push hub, admin, CLI)
fixtures/offline_services.json    what is answered locally
tests/                pytest suite, run against an in-process upstream stub
docs/                 resume point
```

## Quick start

```
pip install -r requirements.txt
python scripts/build_descriptor_set.py          # optional: the CLI builds it on first run
python -m pytest                                 # 25 tests
python scripts/make_tls.py --out tls             # CA + leaf, SAN localhost/127.0.0.1/127.0.0.2
```

Run on the rig (Windows, as the same user that runs the client):

```
python -m sc_offline_services ^
    --descriptors build\sc_reconstructed_descriptors.pb ^
    --fixtures fixtures\offline_services.json ^
    --listen 127.0.0.1:443 --tls-cert tls\leaf.pem --tls-key tls\leaf.key ^
    --upstream 127.0.0.3:443 --upstream-ca <StarBackend CA public PEM> --upstream-authority localhost ^
    --admin 127.0.0.1:18081
```

Swap `--descriptors` for the real `sc_client_descriptors.pb` extracted from the client when it is
on hand; nothing else changes.

## The seat, and the order that works

Every rule below cost a run on 2026-09-26.

1. StarBackend binds `0.0.0.0:443`. Windows lets a specific `127.0.0.1:443` bind sit beside it and
   delivers to the most specific listener, so the client's default endpoint lands here and the
   emulator reaches StarBackend through its wildcard on `127.0.0.3:443`.
2. Start order: StarBackend serve, then this server, then the client. The client opens its first
   channel about 0.08 s after its main thread resumes. Restarting this server while a client is up
   loses that client to the wildcard for good; relaunch the client instead.
3. Trust: the client accepts leaves signed by a CA in `CurrentUser\Root`. Installing the generated
   CA is an operator action, never done by this code:
   `certutil -addstore -user Root tls\ca.cer` (remove with
   `certutil -delstore -user Root "SC Offline Services Local CA"`).
4. The endpoint override on the client replaces only the host. Port and scheme stay 443 and TLS.
5. Do not click the `StarBackend.exe launch` console (Select mode freezes the injector).

## Fixture format

```json
{
  "config": {
    "cvars/variables": null,                                     // NOT_FOUND
    "grpc/endpoints": {"disabled": true, "version": 1, "value": {...}},
    "plain/string": "served verbatim"
  },
  "instances": [ { "shard_id": "*", "status": 7, "template": {"instance_oc_path": "...socpak", "type": 1} } ],
  "push_on_listen": [ {"type": "InstanceBecameActive", "message": {"instance": {"instance_id": "x"}}} ]
}
```

- Keys starting with `_` are notes. The file may carry a UTF-8 BOM.
- Object values under `config` are served as compact JSON strings. `curr_version` equal to the entry's
  `version` answers `FOUND_NO_UPDATE`.
- `shard_id: "*"` on an instance echoes whatever shard the client asked for (`local_shard` offline).
- Enums are numbers so the fixture also fits the real descriptor set, whose enum value names may differ.
- `POST /reload` re-reads the file; open `Watch*` streams re-send their keys.

## Admin endpoint

```
GET  /status          counters, last 200 RPCs, push subscribers, fixture generation
GET  /log?n=200       log tail
POST /push            {"type": "StartUnstowingInstance", "message": {proto-JSON}}
POST /reload
```

## Pass criteria for the next rig runs

1. `Opening channel for ... InstanceManagerService` appears in Game.log, and the server log shows
   `ConfigService.QueryConfig services/instance_manager_external`. Until then the instance-manager
   client is not being built, and `GetAvailableInstances` cannot be reached.
2. `GetAvailableInstances shard='local_shard'` logged here, followed by the first
   `IIM_RequestInstanceImpl_*` line in Game.log.
3. `SCEvt_II_RegisterInstance` handled: `IIM_HandleRegisterInstance_Registered` in Game.log.

## Honest limits

- Field numbers marked ASSUMED in `protos/` were not in the records. A wrong number on a request
  field parses as unknown and is ignored; a wrong number on a response field is not seen by the
  client. The real descriptor set removes both risks.
- The wire names of the push envelope (`envelopes`, `messages`, `any`) are assumed and live in one
  place, `sc_offline_services/push.py`.
- The `grpc/endpoints` document shape and the `services/instance_manager_external` value are unknown
  until `CCIGServices::LoadChannelConfiguration` (`0x140FAC050`) is read on the rig. Both fixture
  entries ship disabled.
- The descriptor set, IDA dumps and Game.log captures from the rig are not in this repository.
  They are extracted from CIG's binary; decide before publishing them here, since this repository
  is public.
