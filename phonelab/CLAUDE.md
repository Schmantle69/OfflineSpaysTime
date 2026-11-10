# phone-app-lab — working notes for Claude

This repo is a lab notebook for studying Android apps with REA. You (Claude)
are the analyst; REA is your tooling, installed per session under
`/opt/rea-tools`, not committed here.

## Setup each session

1. `bash scripts/setup-rea.sh` — installs REA 6.8.0 + apktool 3.0.3, verifies
   the apktool provider and `rea mcp doctor`.
2. `export PATH="/opt/rea-tools/node_modules/.bin:$PATH"` and
   `export REA_APKTOOL_COMMAND=/opt/rea-tools/bin/apktool`.
3. The REA MCP server is pre-registered in `.mcp.json`. If MCP tools aren't
   loaded, run REA from the CLI instead — same operations, same Evidence.

## The one rule for findings

Every claim cites the Evidence that produced it: the `evidence_id`, the REA
operation, and the file under `evidence/<slug>/`. `confidence: observed` means
REA measured it; anything else is an inference and says so. No citation = guess,
and label it a guess. This is what keeps a write-up honest across app versions.

## Formatting native code

Follow `findings/TEMPLATE.md`. Native disassembly goes in an ```asm``` window,
one instruction per line, each line's effect annotated inline, with the address
and an AOB so the same bytes can be re-found in a later build. Resolve addresses
with `rea address-to-file-offset` and state whether an address is file-relative
or image-based.

## Engines

`scripts/setup-rea.sh` wires apktool (Maven Central, reachable). JADX, Ghidra,
IDA and Kuna are caller-supplied — REA won't download them. In a default cloud
session the quickest route is to **upload a JADX jar** and set
`REA_JADX_MCP_JAR`; GitHub release hosts are blocked by the proxy. See
`docs/engines.md`.

## Boundaries

- Binaries under study never get committed — `.gitignore` enforces it; don't
  override it. Keep them in `targets/<slug>/`.
- Study apps the user owns, is authorised to test, or their own builds.
- This is a notebook: record understanding and evidence. Don't turn findings
  into redistributable patched binaries or circumvention payloads.
- The git branch for this work is set by the task; don't push elsewhere without
  being asked.
