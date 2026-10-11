# Saved live generation examples

Current chosen release v4 examples preserve exact runtime-v1.0.5 outputs and
passed the final isolated browser gates, including ordinary mobile swipe
reachability. They also received a separate
[independent AI review](../evidence/chosen-release-human-review.json) with real
legal and invalid-input scenarios. No human playtest or actual WebView device
compatibility is claimed. Copying or replaying an example makes no fresh model
call.

| Current saved example | Selected fresh success | Independent observed play |
| --- | --- | --- |
| [Courier jump](chosen-release-runner/metadata.json) | First run | Real-time three-jump finish and no-jump collision with keys/touch |
| [Three beacons](chosen-release-grid-puzzle/metadata.json) | First run | Reversible single-beacon moves, ordinary win, terminal guard and raw mobile swipes |
| [Higher card](chosen-release-card-game/metadata.json) | First run | All six legal orders, honest scores, duplicate guard and actual finger scrolling |
| [Targets](chosen-release-shooter/metadata.json) | Second run | Visible narrow-screen targets, real aim, duplicate guard and three-miss loss |

The final fresh evaluation accepted 7 of 10 games across four of five cases.
Both held-out drag/storage generations failed mandatory checks, so that case
has no saved successful example, eligible revision or fresh denied-storage
gameplay acceptance. Three of four eligible revisions passed; the grid
mechanical revision failed before submission. Exact failed candidates and
reasons remain in the [current review](../evidence/chosen-release-human-review.json).

Each current directory contains exact game HTML/source/specification and its
immutable final-image validation report, with provider/model/runtime, protocol,
artifact/report hashes and evidence inventory in metadata. No failed candidate is exported as a playable example.

## Historical frozen comparison v2

These files are exact successful outputs from the frozen live evaluation,
copied from immutable artifact storage after mandatory static and isolated
real-input browser checks passed. They are saved examples, not fresh generation
results when copied or replayed. No game HTML was rewritten during export.

These examples preserve the original comparison protocol and runtime-v1.0.3.
They are historical measured outputs, not replacements for qualification of
later runtime/source-policy releases. Any chosen-release examples belong in a
separate directory with their own exact reports and metadata.

The exact three saved games also passed the rendered-controls and
atomic causal-clock v2 harness in a separate [revalidation](../evidence/historical-examples-current-harness-revalidation.json).
Their original HTML, runtime, specification, metadata and comparison reports
remain unchanged; revalidation made no model calls.

The historical card game has a known mobile layout gap: runtime0.3 blocks
ordinary finger scrolling through its long screen. Locator auto-scrolling
masked this in the earlier checks. The [follow-up review](../evidence/mobile-scroll-gap-review.json)
supersedes that mobile-usability assessment. Keep this example as historical
evidence; a current mobile demonstration needs a new qualified runtime/game.
The separate [final touch revalidation](../evidence/historical-examples-final-touch-revalidation.json)
passed the exact grid and shooter and rejected the exact historical card when a
real swipe could not reach an offscreen control. Earlier reports remain intact.

| Saved example | Selected successful run | Mechanic |
| --- | --- | --- |
| [Three beacons](single_author-grid-puzzle/metadata.json) | Single author, first fresh run | Three independent toggles, ordinary key/touch win |
| [Targets](single_author-shooter/metadata.json) | Single author, first fresh run | Real aiming, one hit per target, three misses lose |
| [Higher card](single_author-card-game/metadata.json) | Single author, second fresh run | Three legal card rounds, honest win/loss/draw score |

Each directory contains exact `game.html`, original generated source, canonical
`spec.json`, the exact immutable `validation.json`, and `metadata.json`. Metadata
binds HTML/spec/source/report hashes, provider/model/mode, trusted runtime version,
validator image, browser version and actual PNG/trace evidence inventory.
Selection is the first successful frozen run per case and strategy; failed runs
remain in the evaluation denominator. Revisions and additional independent
mechanics scenarios are recorded in the [review](../evidence/human-review.json).
Only independently reviewed successful games are exported here.

The independent review is an AI source/visual review with additional isolated
browser scenarios, not a human participant playtest. The contest WebView host
is unknown. Chromium mobile touch emulation does not establish Android/iOS
WebView compatibility. Perceived audio quality, entertainment quality and actual
participant assessment remain unmeasured.

For a fresh generation, follow [installation and studio startup](../../README.md#getting-started)
and the [runbook](../runbook.md): install/build the package and studio, configure
the local coordinator and separate preview listener, build the validator image,
then connect generation and validation runners. The studio opens at
`http://127.0.0.1:8000`; eligible previews use the separate port 8001 listener.
Submit a new prompt there to measure a fresh provider call and a new validation
result. Copying a saved example does not demonstrate that path.

Generated JavaScript was executed only in isolated offline containers during
this work. No saved game was opened in a host browser. These documents are
outside runtime examples/provider knowledge and the frozen generation context.
