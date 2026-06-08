# WowClip Editor Contract

An optional editor may visualize and edit `edl.json`, highlight plans, engineered subtitle assets, and portrait plans. It must remain local-first and must not require hosted APIs.

`edl.json` uses `cutpilot.timeline.v1` and is the canonical editable document. Legacy `timeline.json` may be imported for migration, but new edits should be written back to `edl.json`.
