# On-device lab: Claude Code + REA in Termux

This is the "put Claude in a CLI that can see the phone" route. Instead of a
cloud container that can only receive uploads, you run **Claude Code and REA on
the phone itself**, with native access to `/storage/emulated/0` — your `REA`
folder, Downloads, any APK you've pulled — no uploads, ever.

## Why this exists

A Claude session started from the mobile app runs in a datacenter container. It
physically cannot see your phone's filesystem; the only bridge is the upload
channel. Running Claude Code *on the device* removes that wall entirely.

## Install

1. Install **Termux** — from [F-Droid](https://f-droid.org/packages/com.termux/)
   or [GitHub releases](https://github.com/termux/termux-app/releases). **Not**
   the Play Store build; it's deprecated and breaks package installs.
2. Open Termux and run:
   ```bash
   pkg install -y git
   git clone https://github.com/Schmantle69/OfflineSpaysTime
   bash OfflineSpaysTime/phonelab/scripts/termux-bootstrap.sh
   ```
3. When the **storage permission dialog** appears, tap **Allow** — that's what
   maps `~/storage/shared` to `/storage/emulated/0`.

The script installs Node, OpenJDK 17, Claude Code, REA 6.8.0 and apktool 3.0.3,
registers REA with the on-device Claude Code, and prints a `rea doctor` health
report. It's idempotent — re-run it any time.

## What the script sets up

| piece | where | note |
|---|---|---|
| Node + OpenJDK 17 | Termux `pkg` | runtimes for REA / apktool |
| build tools (clang, python, make) | Termux `pkg` | so a REA native addon can compile if no aarch64 prebuild exists |
| REA 6.8.0 | global npm (`$PREFIX/bin/rea`) | 229 tools |
| apktool 3.0.3 | `~/rea-tools/engines/apktool.jar` + wrapper | Maven Central fat jar, arch-independent |
| Claude Code | global npm (`claude`) | set `INSTALL_CLAUDE_CODE=0` to skip |
| REA ↔ Claude Code | `~/.claude.json` (+ REA skill) | via `rea setup -y --client claude_code` |
| env | `~/.bashrc` (`rea lab env` block) | `REA_APKTOOL_COMMAND`, PATH |

## Use it

```bash
# new Termux shell, or: source ~/.bashrc
claude                         # authenticate once; REA tools are registered
# then, against a real on-device path — no upload:
#   "analyze ~/storage/shared/Download/target.apk"
```

Or drive REA directly:

```bash
rea inspect-apk-signature   ~/storage/shared/REA/<file> --format json
rea decode-android-resources ~/storage/shared/Download/target.apk --format json
```

## Honest limits

- **Not run on-device by the author.** The script was written and syntax/logic
  checked in an x86_64 cloud container; it could not be executed on aarch64
  Android from there. `rea doctor` at the end is the real verdict.
- **Node version.** REA needs `^22.23.4 || ^24.22.1 || >=26.12.1`. The script
  checks what Termux ships and warns if it's outside; if REA refuses to start,
  install a supported Node (`pkg install nodejs-lts` or a version manager).
- **Native engines.** apktool and (once wired) JADX run on-device — they're
  Java. **Ghidra and IDA do not** realistically run on a phone; for native
  `.so` decompilation you still need a desktop or the cloud container.
- **JADX.** dex→Java still needs a `jadx-headless-mcp` 0.7.1 jar; drop it on the
  phone and point `REA_JADX_MCP_JAR` at it (the bootstrap leaves a hook for it).
