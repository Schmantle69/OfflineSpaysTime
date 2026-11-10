#!/usr/bin/env bash
# First pass over an APK. Produces evidence bundles and a findings stub.
#
#   bash scripts/triage-apk.sh /absolute/path/to/app.apk [slug]
#
# Runs only the engine-free and apktool-backed steps, so it works in a default
# cloud session with no JADX, Ghidra, IDA or device attached.
set -euo pipefail

TOOLS="${REA_TOOLS_DIR:-/opt/rea-tools}"
REA="$TOOLS/node_modules/.bin/rea"
export REA_APKTOOL_COMMAND="${REA_APKTOOL_COMMAND:-$TOOLS/bin/apktool}"

APK="${1:?usage: triage-apk.sh /absolute/path/to/app.apk [slug]}"
[ -f "$APK" ] || { echo "no such file: $APK" >&2; exit 1; }
case "$APK" in /*) ;; *) echo "path must be absolute: $APK" >&2; exit 1 ;; esac
[ -x "$REA" ] || { echo "REA missing; run scripts/setup-rea.sh" >&2; exit 1; }

SLUG="${2:-$(basename "$APK" | sed -E 's/\.(apk|apks|xapk|apkm|aab)$//I' | tr -cd 'A-Za-z0-9._-')}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/targets/$SLUG"
EV="$ROOT/evidence/$SLUG"
mkdir -p "$OUT" "$EV"

say() { printf '\n== %s\n' "$*" >&2; }

# Identity first. Anything downstream is quoted against this hash, so a
# finding can never drift onto a different build without the mismatch showing.
say "identity"
SHA="$(sha256sum "$APK" | cut -d' ' -f1)"
SIZE="$(stat -c %s "$APK")"
printf 'file: %s\nsha256: %s\nbytes: %s\ntriaged: %s\n' \
  "$(basename "$APK")" "$SHA" "$SIZE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  | tee "$OUT/IDENTITY.txt"

# Signing schemes, signers, certificate facts, digests. No engine required.
say "apk signature"
"$REA" inspect-apk-signature "$APK" --format json > "$EV/signature.json" 2>"$EV/signature.err" \
  && echo "  -> $EV/signature.json" >&2 \
  || { echo "  signature inspection failed:" >&2; head -5 "$EV/signature.err" >&2; }

# Manifest, metadata and string tables via apktool.
say "android resources (apktool)"
"$REA" decode-android-resources "$APK" --format json > "$EV/resources.json" 2>"$EV/resources.err" \
  && echo "  -> $EV/resources.json" >&2 \
  || { echo "  resource decode failed:" >&2; head -5 "$EV/resources.err" >&2; }

# Framework fingerprint. A Flutter or IL2CPP build means the interesting logic
# is in a native .so, not in dex, and the whole study plan changes.
say "framework fingerprint"
"$REA" identify-flutter-build "$APK" --format json > "$EV/flutter.json" 2>/dev/null \
  && echo "  -> $EV/flutter.json" >&2 || echo "  not a Flutter build (or probe unavailable)" >&2

say "zip layout"
unzip -l "$APK" 2>/dev/null | awk '{print $4}' | grep -E '\.(so|dex|json|js|bundle)$' \
  | sed -E 's|^(lib/[^/]+)/.*|\1/*.so|' | sort | uniq -c | sort -rn | head -25 \
  | tee "$OUT/LAYOUT.txt" >&2 || true

if [ ! -f "$ROOT/findings/$SLUG.md" ]; then
  sed -e "s|{{SLUG}}|$SLUG|g" -e "s|{{SHA256}}|$SHA|g" \
      -e "s|{{FILE}}|$(basename "$APK")|g" -e "s|{{DATE}}|$(date -u +%Y-%m-%d)|g" \
      "$ROOT/findings/TEMPLATE.md" > "$ROOT/findings/$SLUG.md"
  say "findings stub: findings/$SLUG.md"
fi

say "done"
printf 'evidence: %s\ntarget:   %s\nfindings: %s\n' "$EV" "$OUT" "$ROOT/findings/$SLUG.md" >&2
