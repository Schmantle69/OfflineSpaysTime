#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# termux-bootstrap.sh — stand up an on-device REA lab inside Termux (Android).
#
# Puts Claude Code AND REA on the phone itself, with native access to your
# whole filesystem (no uploads). After this runs, `claude` launched from
# Termux can read /storage/emulated/0/REA, your Downloads, pulled APKs — all
# of it — and drive REA's 229 tools + apktool against them directly.
#
#   pkg install -y bash && bash termux-bootstrap.sh
#
# IDEMPOTENT: safe to re-run; each step is skipped if already satisfied.
#
# NOT verified on-device. This was authored in an x86_64 cloud container and
# cannot be executed on aarch64 Android from there. Every step is based on
# documented Termux behavior; the apktool fat jar and REA/Claude Code are pure
# Node/Java and arch-independent, but a REA native addon may need to compile
# on first install (build tools are installed for exactly that). Read the
# summary `rea doctor` prints at the end — it is the ground truth for whether
# the on-device lab is healthy.
# =============================================================================
set -euo pipefail

REA_VERSION="${REA_VERSION:-6.8.0}"
APKTOOL_VERSION="${APKTOOL_VERSION:-3.0.3}"
TOOLS="${REA_TOOLS_DIR:-$HOME/rea-tools}"
APKTOOL_URL="https://repo1.maven.org/maven2/org/apktool/apktool-cli/${APKTOOL_VERSION}/apktool-cli-${APKTOOL_VERSION}.jar"
INSTALL_CLAUDE_CODE="${INSTALL_CLAUDE_CODE:-1}"   # set 0 to skip the Claude Code CLI

log()  { printf '\n\033[1;36m[termux-rea]\033[0m %s\n' "$*" >&2; }
warn() { printf '\n\033[1;33m[termux-rea] WARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\n\033[1;31m[termux-rea] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }

# --- 0. confirm we are in Termux -------------------------------------------
[ -n "${PREFIX:-}" ] && echo "$PREFIX" | grep -q com.termux \
  || command -v pkg >/dev/null \
  || die "This does not look like Termux (no \$PREFIX/com.termux, no pkg). Run it inside the Termux app."

log "Termux detected. PREFIX=$PREFIX"

# --- 1. system packages -----------------------------------------------------
# nodejs  : REA + Claude Code runtime
# openjdk-17: apktool / any JVM engine
# procps  : REA's owned-process ownership check needs a real `ps`
# build-essential python clang: in case a REA native addon has no aarch64 prebuild
# git curl which: fetch + scripting
log "refreshing package index (pkg update)"
yes | pkg update  >/dev/null 2>&1 || warn "pkg update had warnings; continuing"

log "installing: nodejs openjdk-17 git curl which procps build-essential python clang"
yes | pkg install nodejs openjdk-17 git curl which procps build-essential python clang \
  || die "package install failed. Re-run; if nodejs is the problem try: pkg install nodejs-lts"

log "node $(node --version 2>/dev/null), $(java -version 2>&1 | head -1)"

# REA requires node ^22.23.4 || ^24.22.1 || >=26.12.1. npm only warns on a
# mismatch, so verify and surface it rather than let REA fail opaquely later.
node -e 'const [a,b,c]=process.versions.node.split(".").map(Number);
  const ge=(mj,mn,pt)=>a>mj||(a===mj&&(b>mn||(b===mn&&c>=pt)));
  const ok=(ge(22,23,4)&&a<23)||(ge(24,22,1)&&a<25)||ge(26,12,1);
  if(!ok){console.error("  node "+process.versions.node+" is OUTSIDE REA\x27s supported ranges (^22.23.4 || ^24.22.1 || >=26.12.1).");
  console.error("  It may still work; rea doctor will confirm. If REA refuses to start, install a supported node.");}' || true

# --- 2. storage access ------------------------------------------------------
# Creates ~/storage/* symlinks into shared storage. REQUIRES an Android
# permission dialog the first time — tap Allow. ~/storage/shared maps to
# /storage/emulated/0, so your REA folder becomes ~/storage/shared/REA.
if [ ! -d "$HOME/storage/shared" ]; then
  log "requesting storage access — TAP ALLOW on the Android dialog"
  termux-setup-storage || warn "termux-setup-storage did not complete; run it manually, then re-run this script"
  sleep 2
fi
[ -d "$HOME/storage/shared" ] \
  && log "shared storage linked: ~/storage/shared -> /storage/emulated/0 (your REA folder: ~/storage/shared/REA)" \
  || warn "~/storage/shared not present yet; grant storage permission and re-run"

# --- 3. REA -----------------------------------------------------------------
if ! command -v rea >/dev/null; then
  log "installing rea-agents@${REA_VERSION} globally (may compile a native addon on first run)"
  npm install -g "rea-agents@${REA_VERSION}" --no-audit --no-fund \
    || die "rea-agents install failed. If it was a native build error, ensure build-essential+python+clang installed, then re-run."
else
  log "rea already installed: $(rea --version 2>/dev/null | tail -1)"
fi

# --- 4. apktool (arch-independent fat jar from Maven Central) ---------------
mkdir -p "$TOOLS/bin" "$TOOLS/engines"
if [ ! -s "$TOOLS/engines/apktool.jar" ]; then
  log "fetching apktool ${APKTOOL_VERSION} from Maven Central"
  if curl -fsSL --retry 3 --retry-delay 2 -o "$TOOLS/engines/apktool.jar.part" "$APKTOOL_URL"; then
    mv "$TOOLS/engines/apktool.jar.part" "$TOOLS/engines/apktool.jar"
  else
    warn "Maven fetch failed; falling back to Termux package"
    yes | pkg install apktool && APKTOOL_PKG=1 || die "apktool unavailable via Maven and pkg"
  fi
fi
if [ -s "$TOOLS/engines/apktool.jar" ]; then
  # stdout must stay clean: REA parses the first line of --version as semver.
  printf '%s\n' '#!/data/data/com.termux/files/usr/bin/bash' \
                "exec java -jar $TOOLS/engines/apktool.jar \"\$@\"" > "$TOOLS/bin/apktool"
  chmod +x "$TOOLS/bin/apktool"
  REA_APKTOOL_COMMAND="$TOOLS/bin/apktool"
else
  REA_APKTOOL_COMMAND="$(command -v apktool || true)"
fi
[ -n "${REA_APKTOOL_COMMAND:-}" ] && log "apktool: $("$REA_APKTOOL_COMMAND" --version 2>/dev/null | tail -1) ($REA_APKTOOL_COMMAND)"

# --- 5. optional: Claude Code on-device -------------------------------------
if [ "$INSTALL_CLAUDE_CODE" = "1" ]; then
  if ! command -v claude >/dev/null; then
    log "installing Claude Code CLI (@anthropic-ai/claude-code)"
    npm install -g @anthropic-ai/claude-code --no-audit --no-fund \
      || warn "Claude Code install failed; you can still use REA from the CLI. Retry: npm install -g @anthropic-ai/claude-code"
  else
    log "claude already installed: $(claude --version 2>/dev/null | tail -1)"
  fi
fi

# --- 6. persist env in the shell rc ----------------------------------------
# So REA_APKTOOL_COMMAND is in the environment whenever you launch `claude` or
# `rea` from Termux (the MCP server inherits it; the registration bakes in no env).
RC="$HOME/.bashrc"
MARK="# >>> rea lab env >>>"
if ! grep -qF "$MARK" "$RC" 2>/dev/null; then
  log "writing REA env to $RC"
  {
    echo ""
    echo "$MARK"
    echo "export REA_APKTOOL_COMMAND=\"${REA_APKTOOL_COMMAND:-}\""
    echo "export PATH=\"$TOOLS/bin:\$PATH\""
    echo "[ -n \"\${REA_JADX_MCP_JAR:-}\" ] || true  # set this to wire dex->Java decompilation"
    echo "# <<< rea lab env <<<"
  } >> "$RC"
fi
export REA_APKTOOL_COMMAND PATH="$TOOLS/bin:$PATH"

# --- 7. register REA with on-device Claude Code -----------------------------
if command -v claude >/dev/null && [ "$INSTALL_CLAUDE_CODE" = "1" ]; then
  log "registering REA with Claude Code (writes ~/.claude.json, backs it up, installs the REA skill)"
  rea setup -y --client claude_code || warn "rea setup reported a problem; you can register later with: rea setup -y --client claude_code"
fi

# --- 8. honest health report ------------------------------------------------
log "running rea doctor (this is the ground truth for on-device health)"
rea doctor --filter-output healthy,scope_checks 2>&1 | sed 's/^/    /' || warn "rea doctor failed to run"
log "running rea mcp doctor"
rea mcp doctor --filter-output healthy,inventory.tools.observed 2>&1 | sed 's/^/    /' || warn "rea mcp doctor failed to run"

cat >&2 <<SUMMARY

================= on-device REA lab =================
  REA:      $(command -v rea || echo 'NOT installed')
  apktool:  ${REA_APKTOOL_COMMAND:-NOT configured}
  Claude:   $(command -v claude || echo 'not installed (INSTALL_CLAUDE_CODE=0)')
  storage:  ~/storage/shared -> /storage/emulated/0   (REA folder: ~/storage/shared/REA)

  Start a new Termux shell (or: source ~/.bashrc), then:
    claude                      # on-device Claude; authenticate once
    # inside it, point at a real file with no upload:
    #   analyze ~/storage/shared/Download/some.apk

  Or drive REA straight from the shell:
    rea inspect-apk-signature ~/storage/shared/Download/some.apk --format json
    rea decode-android-resources ~/storage/shared/Download/some.apk --format json

  Still to wire (optional): dex -> Java decompilation.
    Put a jadx-headless-mcp 0.7.1 jar on the phone, then:
      export REA_JADX_MCP_JAR=/absolute/path/to/jadx-headless-mcp-0.7.1.jar
    (add it to the 'rea lab env' block in ~/.bashrc to make it stick)
====================================================
SUMMARY
