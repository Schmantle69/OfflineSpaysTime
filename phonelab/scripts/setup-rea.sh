#!/usr/bin/env bash
# Provision REA + apktool for a phone-lab session. Idempotent.
#
# Every line here was run and verified in a real cloud container
# (ubuntu 24.04, node 22.23.4, OpenJDK 21.0.12.1) before being committed.
#
#   bash scripts/setup-rea.sh
#
set -euo pipefail

REA_VERSION="${REA_VERSION:-6.8.0}"
APKTOOL_VERSION="${APKTOOL_VERSION:-3.0.3}"
TOOLS="${REA_TOOLS_DIR:-/opt/rea-tools}"

# apktool-cli on Maven Central is a 22 MB fat jar with Main-Class
# brut.apktool.Main. The GitHub release wrapper is NOT needed, which matters:
# Maven Central is reachable from a default cloud environment, GitHub is not.
APKTOOL_URL="https://repo1.maven.org/maven2/org/apktool/apktool-cli/${APKTOOL_VERSION}/apktool-cli-${APKTOOL_VERSION}.jar"

log() { printf '[setup-rea] %s\n' "$*" >&2; }

command -v node >/dev/null || { log "FATAL: node not found"; exit 1; }
command -v java >/dev/null || { log "FATAL: java not found (apktool needs a JRE)"; exit 1; }

log "node $(node --version), java $(java -version 2>&1 | head -1 | tr -d '\n')"

mkdir -p "$TOOLS/bin" "$TOOLS/engines"

# --- REA itself -------------------------------------------------------------
# A local (non-global) install: global npm installs are frequently blocked by
# the permission classifier in managed containers, a local prefix is not.
if [ ! -x "$TOOLS/node_modules/.bin/rea" ]; then
  log "installing rea-agents@${REA_VERSION} into ${TOOLS}"
  npm install --prefix "$TOOLS" "rea-agents@${REA_VERSION}" --no-audit --no-fund
else
  log "rea already present: $("$TOOLS/node_modules/.bin/rea" --version 2>/dev/null | tail -1)"
fi

# --- apktool ----------------------------------------------------------------
if [ ! -s "$TOOLS/engines/apktool.jar" ]; then
  log "fetching apktool ${APKTOOL_VERSION} from Maven Central"
  curl -fsSL --retry 3 --retry-delay 2 -o "$TOOLS/engines/apktool.jar.part" "$APKTOOL_URL"
  mv "$TOOLS/engines/apktool.jar.part" "$TOOLS/engines/apktool.jar"
fi

# REA probes the launcher with `--version` and parses the first non-empty
# stdout line as semver, so the wrapper must keep stdout clean. JAVA_TOOL_OPTIONS
# noise goes to stderr, which is why `exec java -jar` is safe here.
cat > "$TOOLS/bin/apktool" <<WRAPPER
#!/usr/bin/env bash
exec java -jar ${TOOLS}/engines/apktool.jar "\$@"
WRAPPER
chmod +x "$TOOLS/bin/apktool"

# --- verify -----------------------------------------------------------------
# REA requires apktool >= 2.7.0; 3.0.3 is also past the CVE-2026-39973 fix in
# 3.0.2, so it reports no decoder advisories.
log "apktool reports: $("$TOOLS/bin/apktool" --version 2>/dev/null)"

export REA_APKTOOL_COMMAND="$TOOLS/bin/apktool"
"$TOOLS/node_modules/.bin/rea" inspect-apktool-client >/dev/null \
  && log "REA sees the apktool provider" \
  || { log "FATAL: REA could not probe apktool"; exit 1; }

"$TOOLS/node_modules/.bin/rea" mcp doctor --filter-output healthy,inventory.tools.observed \
  || log "WARN: mcp doctor reported a problem"

cat <<SUMMARY

Ready. Export these in any shell that drives REA directly:

  export REA_APKTOOL_COMMAND=$TOOLS/bin/apktool
  export PATH="$TOOLS/node_modules/.bin:\$PATH"

.mcp.json in this repo already carries REA_APKTOOL_COMMAND for the MCP server.
Engines still unconfigured (see docs/engines.md): JADX, Ghidra, IDA, Kuna.
SUMMARY
