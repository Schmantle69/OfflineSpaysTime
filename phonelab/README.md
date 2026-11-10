# phone-app-lab

A lab notebook for studying Android apps from Claude mobile, driven by
[REA](https://github.com/morluto/rea) (Reverse Engineer Anything, MIT).

REA is the toolbox — installed per session, not committed here. This repo holds
the **config to stand it up**, a **triage harness**, and the **written-up
findings** for each app studied. Binaries under study stay out of git.

## What's here

```
.mcp.json            REA registered as an MCP server for Claude Code
scripts/setup-rea.sh install + verify REA and apktool in the session
scripts/triage-apk.sh first engine-free pass over an APK -> evidence + stub
findings/TEMPLATE.md  the finding format (asm window for native code)
findings/<slug>.md    one write-up per app
docs/engines.md       which decompilers are auto vs. manual, and why
docs/workflow.md      the study loop, start to finish
targets/<slug>/       local-only: the APK and its decoded trees (git-ignored)
evidence/<slug>/      local-only: raw REA Evidence bundles (git-ignored)
```

## Quick start (in a Claude mobile session)

```bash
bash scripts/setup-rea.sh                      # REA 6.8.0 + apktool 3.0.3
bash scripts/triage-apk.sh /path/to/app.apk x  # identity, signing, manifest
```

Then read `findings/x.md` and follow `docs/workflow.md` to go deeper.

> **Nested in OfflineSpaysTime:** this lab lives in `phonelab/`, so Claude
> Code's root `.mcp.json` auto-discovery won't pick up `phonelab/.mcp.json`.
> To use REA's MCP tools, either copy `phonelab/.mcp.json` to the repo root,
> or just drive REA from the CLI (`/opt/rea-tools/node_modules/.bin/rea ...`)
> after `scripts/setup-rea.sh` — same operations, same Evidence.

## What runs where

- **Default cloud session (what you get from mobile):** REA + apktool. Enough
  for identity, signing, manifest/resources/strings, framework fingerprint,
  and full JavaScript/Electron app analysis.
- **+ an uploaded JADX jar:** Java/Kotlin decompilation from dex. Upload the
  jar into the session; no network change needed (`docs/engines.md`).
- **+ Ghidra or IDA:** native `.so` / IL2CPP decompilation.
- **+ a device over adb (desktop-served folder, not mobile-only):** live
  inspection, logcat, Frida instrumentation.

## Scope and intent

Study apps you own or are authorised to test, and your own builds you want to
understand before extending. Findings are recorded as understanding plus
traceable evidence. Redistribution-restricted binaries are kept local by
`.gitignore`; this is a notebook, not a distribution channel.

REA is MIT-licensed; get it only from its official sources
(`github.com/morluto/rea`, `rea.tools`, the `rea-agents` npm package).
