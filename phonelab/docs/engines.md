# Analysis engines

REA is an orchestrator. It ships no decompiler of its own; each native/dex
engine is a caller-supplied binary that REA refuses to download, so you point
an environment variable at one. `rea doctor` lists what is and isn't wired.

What this repo provisions automatically (`scripts/setup-rea.sh`):

| engine | role | source | status |
|---|---|---|---|
| **apktool** 3.0.3 | manifest, resources, strings | Maven Central (reachable) | **auto** |
| REA 6.8.0 | orchestration, 229 MCP tools | npm (reachable) | **auto** |

What stays manual, and why:

| engine | role | env var | how to supply it |
|---|---|---|---|
| **JADX** (jadx-headless-mcp 0.7.1) | Java/Kotlin decompilation from dex | `REA_JADX_MCP_JAR` | upload the jar into the session, point the var at its absolute path |
| **Ghidra** 12.1.x | native `.so` / il2cpp decompilation | `GHIDRA_INSTALL_DIR` | extract a release into the session, point the var at the dir |
| **IDA** | native, if you own a licence | `REA_IDA_MCP_CONFIG` | your upstream IDA MCP registration JSON |
| **Kuna** 1.833 | native, alt engine | `REA_KUNA_COMMAND` | absolute path to the kuna executable |

## Why JADX/Ghidra aren't auto

In a default cloud environment the egress allow-list reaches Maven Central and
npm but **not** github.com (the proxy returns 403). apktool-cli lives on Maven
Central as a self-contained fat jar, so it installs cleanly. JADX's
`jadx-headless-mcp` and Ghidra releases are published only on GitHub.

Two ways around it, in order of preference from a phone:

1. **Upload the jar.** Attach `jadx-headless-mcp-0.7.1.jar` to the Claude
   session the same way an APK is attached, then:
   `export REA_JADX_MCP_JAR=/absolute/path/to/jadx-headless-mcp-0.7.1.jar`
   No network needed. This is the mobile-friendly path.

2. **Allow the hosts.** Grant an environment egress to `github.com`,
   `api.github.com`, `objects.githubusercontent.com` and
   `codeload.github.com`, then fetch the releases in the setup script. This
   needs approval and is a per-environment decision — see the project README.

## Verifying an engine after you wire it

```bash
export PATH="/opt/rea-tools/node_modules/.bin:$PATH"
rea doctor --filter-output scope_checks       # per-engine ok/remediation
rea capabilities                              # what each wired provider can do
```
