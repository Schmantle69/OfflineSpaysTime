# Resume point: private hangars and ATC offline spawning (2026-09-27)

Build **4.10.193.11644** (`StarCitizen.exe` MD5 `325f0cdab057630027de538e8b0c7946`, image base `0x140000000`).
Everything below is condensed from the measured records of 2026-09-26 (`OFFLINE_AUTHORITY_ACHIEVED`,
`NEEDS_FOR_OFFLINE_HANGAR_AND_SHIP_SPAWN`, `INDEX`, offline-identity `README`). Those records stay on the rig.
This repo is public, so account handles, account ids and player geids are deliberately left out of this file.

## 1. Where the live session is

| item | value |
|---|---|
| session | `session_01RCnGcZcTevtP1MTrixM8VA`, title "Private hangars and ATC offline spawning" |
| kind | Remote Control session bound to the Windows rig (`remote-control-sdk`) |
| last active | 2026-09-26 16:19Z, then `computer_unreachable` at 17:04Z |
| transcript | `C:\Users\user\.claude\projects\...` on the rig, not in any cloud container |
| last stated next step | "boot with `boot_offline.ps1`, type `map pu_all` once, say *in-world*; then NC attach, flag restore, ETW lamp armed, client-only patch, touch the kiosk once" |

The last ~2.5 h of that session (16:19Z back to the end of Addendum E at 13:40Z) are **not** in the four
records: the "flag restore", "ETW lamp" and "client-only patch" steps exist only in that transcript.
Resume it on the rig: Claude Desktop app, or `claude remote-control` in the working folder, then pick the session.

## 2. What is proven to work offline (client side of the seam)

- `map pu_all` at the frontend console makes the **local replicant host `SC_Default`** on `<local>:12300`
  (same nub that served `SC_Frontend`; the pair is destroyed and recreated with the new gamerules).
- `Offline_EntitlePlayer` completes, `SpawnPlayer_NoShardPersistence`, EntityGraph seeds `local_shard`
  (8 systems), `SeedingProcessor::CreateShard Success shardId[local_shard]`.
- `ATC_DataManager-001` (class `ATC_DataManager_Port_SemiLawful`) is live with three Subsumption
  `ATC_OperatorAIModule` operators; `g_ATC_requestTakeOff <atc> [class]` via NC `con.exec` runs the whole
  authority side up to `ATC_RequestingHangarInstance` -> `IIM_AsyncRequestInstanceBySize_Requesting`
  (`origin[ASOP]`, `instanceSize[2]`), then waits forever in `LandingAreaInstanceInQueue`.
- Player carries `Insurance` (857), `EntityComponentInventory` (224), `Wallet` (855). The insurance gate on
  `OnRequestFetchVehicles` is **not** the kiosk blocker.
- Ship list provider is on `PersonalMobiGlas_PU` (`EntityComponentShipListProvider`, tid 1144), not on the
  kiosk (`EntityComponentShipInsuranceProvider`, tid 1008).
- Transit gateways are seeded (`TransportManager_Area18_Spaceport_Hangars` registered 7 carriages).

## 3. The block, pinned

| step | fact |
|---|---|
| service catalogue | local `StarBackend.exe` serves exactly `IdentityService/GetCurrentPlayer` and `LoginService/InitiateLogin` |
| channels | client opens `ConfigService`, `AnalyticsService`, `PushService` only; no `InstanceManagerService` channel |
| broker | `EntityComponentInstanceBroker` (tid 566) on **0 of 47,758** entities |
| IIM wrapper | `sub_143A3B860`: `svc = (*(*qword_149E2E7E8+24))()`, `api = (*(*svc+80))()`, `fut = (*(*api+16))(owner, location)`; offline `svc`/`api` is null, payload released, nothing logs |
| request record | 88 bytes: `+0x00` requestId, `+0x08` origin, **`+0x0C` active latch (stays 1)**, `+0x10` size; pump `UpdateRequests` (`0x143A5D5A0`) skips on `+0x0C` every 5 s |
| shared seam | elevator panel -> `0x14370EDF0` -> `0x143A3D860` -> `RequestPlayerHangarPermissions` (`0x1439618A0`) consumes the same query ("Failed FindHangarsAtLocation call" `0x1486C8558`) |
| socpak | `InstanceTemplate.instance_oc_path` is a backend field; hangar socpaks are in the P4K under `objectcontainers/pu/loc/mod/common/hangar/util_a/` |

## 4. Side server state (Addendum D/E)

- `offline_services\sc_offline_services.py` on the rig: gRPC server on the client's own `FileDescriptorSet`
  (132 files, `sc_client_descriptors.pb`), serving ConfigService, `InstanceManagerService.GetAvailableInstances`
  (from `offline_services.json`), `PushService.Listen` with a push queue, passthrough of the other services.
- **Seat**: bind `127.0.0.1:443` beside StarBackend's `0.0.0.0:443` (specific bind wins), proxy upstream to
  `127.0.0.3:443`. Endpoint override replaces only the host; port/scheme are per-service defaults (443/TLS).
- Trust: the user's own CA (`SC Offline Services Local CA`) is in `CurrentUser\Root`; removable with
  `certutil -delstore -user Root "SC Offline Services Local CA"`.
- Proven: full boot, login and world load proxied cleanly through the seat, no upstream rejection.
- **Measured negative**: the client never requests `services/instance_manager_external` or any `services/*`
  key. Its boot config keys are `cvars/variables` (x2), `grpc/endpoints`, `cig_trace/trace_filter`, all
  answered NOT_FOUND today. `grpc/endpoints` is a channel-configuration document
  (`endpoints`, `queues`, `channels{...}`) loaded by `CCIGServices::LoadChannelConfiguration` (`0x140FAC050`).

## 5. Open question and next acts, in order

**Open:** what gates construction of the instance-manager client (`SInstanceManagerExternalConfig` reader
`0x140C87B50`, `0x140C45350`) when ConfigService is never asked for it.

1. Read `LoadChannelConfiguration` (`0x140FAC050`) for the `grpc/endpoints` document shape. Serve a
   `grpc/endpoints` value that names an `instance_manager` endpoint and watch `Game.log` for
   `Opening channel for ... InstanceManagerService`.
2. Once the channel opens, answer `GetAvailableInstances` for `shard_id="local_shard"` with one
   `Instance{status=STOWED, template{type=PLAYER_HANGAR, instance_oc_path=<P4K socpak>}}` and watch for the
   first `IIM_RequestInstanceImpl_*` line (`AttemptingUnstow` / `CreatingStagingHangar` / a failure tag).
3. Re-probe `ent.with EntityComponentInstanceBroker` (tid 566) after the service exists: created by the
   client, or must be placed.
4. Ships: entitlements arrive as entitlement.v2 `Entitlement{entity_class_guid, ...}` via
   `QueryEntitlementsStream`; vehicle ids come from `EntityGraphService.InventoryQuery`; a pad spawn is an
   EG unstow (`CFuture<CigResult<map<SInventoryId, vector<EntityId>>>>::OnResolved` = `sub_142AF4390`,
   11 callers). `g_ATC_requestTakeOff` hardcodes VehicleId 0, so a real id needs `RequestVehicle`
   (`0x144C2BA50`) or an in-frame `RequestTakingOff`.

## 6. Traps carried forward (each cost a run)

- `g_iim.notice=1` makes `UpdateRequests` break before its work: the lamp stops the pump. Keep it 0.
- NC `mem.restore` is `<addr> <expected> <write>` (a CAS); the help text has it reversed.
- `soc_dumpShardGraph` is on NC's crash list. Do not run it from the console either.
- Two `map pu_all` in one client session crash the client. One driver per action.
- The side server must bind `127.0.0.1:443` after StarBackend's serve and before the client's first channel
  (~0.08 s after resume). Bouncing it with a client up loses that client to the wildcard for good.
- `StarBackend.exe launch` console must not be clicked (Select mode freezes the injector).
- A Python function containing `yield` is a generator on every path; split unary handlers.
- `Set-Content -Encoding utf8` writes a BOM; NC param files and JSON must be BOM-less.
- `g_iim.debugCreateAll` produces an `origin[InstanceManagerDebug]` instance and proves nothing about the
  elevator path. Ruled out.

## 7. Rig boot recipe (from the records, not re-run here)

1. `boot_offline.ps1` as Administrator (kills retail client, stops EAC, patches identity from `.pristine`,
   serves StarBackend on `0.0.0.0:443` + `:8000`, injects StarHook).
2. Start the side server on `127.0.0.1:443` (upstream `127.0.0.3:443`).
3. `StarBackend.exe launch` the client; confirm the first `Opening channel for` lines land in the side
   server log.
4. At the frontend console: `map pu_all` once. Wait for `OnClientEnteredGame`.
5. Attach NC External (`\\.\pipe\NC_External_cmd`); `con.exec g_ATC_dumpAllInfo` as the baseline.

## 8. What this repo holds

`README.md` and this file. The side server, decoded protos, IDA dumps and Game.log captures are on the rig.
Before adding the raw records here, strip account handles, account ids, player geids and the third-party
handles/geids quoted from live logs, since the repository is public.
