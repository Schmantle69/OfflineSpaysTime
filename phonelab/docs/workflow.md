# Workflow: studying an app from the phone

The loop is the same whether the target is a game, a fintech app, or your own
build you want to understand before shipping a similar feature.

## 0. Once per session

```bash
bash scripts/setup-rea.sh
export PATH="/opt/rea-tools/node_modules/.bin:$PATH"
export REA_APKTOOL_COMMAND=/opt/rea-tools/bin/apktool
```

## 1. Get the APK in

From Claude mobile, attach the `.apk`/`.xapk` to the message. It lands under
the session uploads directory; use that absolute path. Keep binaries in
`targets/<slug>/` locally — they never get committed (see `.gitignore`).

## 2. Triage (engine-free)

```bash
bash scripts/triage-apk.sh /absolute/path/to/app.apk mygame
```

This records identity (sha256), signing facts, the decoded manifest/strings,
and a framework fingerprint, then drops a `findings/mygame.md` stub. All of it
runs with just apktool — no JADX, Ghidra, or device.

## 3. Decide where the logic lives

Read `targets/<slug>/LAYOUT.txt` and the manifest in the resources evidence:

- **dex-heavy, thin `lib/`** → Java/Kotlin. Wire JADX (`docs/engines.md`) and
  use REA's `inspect-android-class` / `inspect-android-method` /
  `search-android-classes` / `trace-android-references`.
- **big `lib/arm64-v8a/*.so`, Flutter/IL2CPP marker** → native. Wire Ghidra;
  the logic is compiled, so you are reading asm, and findings use the asm
  window in `findings/TEMPLATE.md`.
- **`assets/*.bundle` / lots of `.js`** → React Native or Cordova. REA's
  JavaScript application analysis handles these with no native engine at all.

## 4. Document, don't hoard

Fill `findings/<slug>.md` as you go. One claim, one citation. The point of the
repo is the written-up understanding — the evidence bundles are scaffolding.

## 5. Live device (optional, not from mobile alone)

REA's ~20 `*-adb-*` verbs and Frida need a real device on `adb`. That requires
a desktop running the Claude app and serving a folder with the platform-tools
and the phone attached — it can't be reached from a cloud session on its own.
When you have it: `rea list-adb-devices`, then `inspect-adb-package`,
`read-adb-logcat`, `pull-adb-package`, `instrument-with-frida`.

## Scope

Study apps you own, apps you're authorised to test, and your own builds. Keep
redistribution-restricted binaries out of git (the `.gitignore` enforces it).
Record findings as understanding and evidence; this repo is a lab notebook,
not a redistribution channel.
