# evidence/

Raw REA Evidence bundles land here, one subdirectory per target slug. They are
**git-ignored** — they can be large, and they are reproducible from the APK
plus the recorded REA command. What belongs in version control is the distilled
`findings/<slug>.md`, which cites these files.

Each REA result is a signed Evidence record: an `evidence_id`, the provider and
its version, the exact operation and parameters, a `confidence` grade
(`observed` vs inferred) and an explicit `limitations` list. When you quote a
finding, quote the `evidence_id` so the claim is traceable to the bundle.

Re-generate everything for a target with:

```bash
bash scripts/triage-apk.sh /absolute/path/to/app.apk <slug>
```
