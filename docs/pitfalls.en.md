English | [简体中文](./pitfalls.zh.md)

# API Behaviours and Pitfalls

This document records how EasyEDA Pro behaves under API automation. None of it appears in the official
reference. Skim the headings before you start.

Terms used throughout:

- **Bridge** — the Node service in the official `easyeda-api-skill` that forwards HTTP requests to the
  EasyEDA client over WebSocket for execution.
- **Job** — one block of JS sent through the bridge for execution. One HTTP request equals one job.
- **Primitive** — a programmable object on the board: track, via, pad, copper pour. Each has a `primitiveId`.
- **Silent write failure** — an API call returns success and reads back the new value, yet the change was
  never persisted to the document. This one comes up repeatedly below.

---

## 1. Silent write failures — the first principle

One class of EasyEDA API behaviour is genuinely dangerous: **a property write returns success, reads back
as the new value, and reverts to the old value after a restart**. The change reached the in-memory view but
never the document.

Confirmed cases:

| Call | Symptom | Correct approach |
|---|---|---|
| `pcb_PrimitiveVia.modify(id, {diameter, holeDiameter})` | Hole/pad diameter change reports success and reads back as new; reverts on restart | Delete and recreate: `delete([id])` then `create(net, x, y, holeDiameter, padDiameter)` |
| `pcb_PrimitivePour.modify(id, {lineWidth})` | Pour outline width: the response shows the new value but it does not persist. Neither single-field nor whole-object write works | Currently only editable through the UI |
| `pcb_Drc.overwriteCurrentRuleConfiguration(whole wrapper object)` | Fails silently — no error, no effect | Pass only the `cfg.config` sub-object, and **check that the return value is `true`** |

Hence the first principle of this document:

> **Reading back the new value is not verification. After changing a critical property, restart EasyEDA
> (launching it with the project path argument) and read it again.**

This applies equally to humans and to automation: a "reads back as new" result obtained by a script is not
evidence of persistence either.

---

## 2. Schematic to PCB sync (importChanges)

This is the stage most likely to convince you the API is broken.

**1. Components must carry `addIntoPcb=true`, or the sync places zero components.**
The full signature is
`sch_PrimitiveComponent.create(component, x, y, subPartName, rotation, mirror, addIntoBom, addIntoPcb)`.
Omit the last two arguments and the components exist only in the schematic and never reach the PCB.
An already-built board can be repaired: per component,
`sch_PrimitiveComponent.modify(id, {addIntoPcb: true, addIntoBom: true})`, then `sch_Document.save()`.

**2. `pcb_Document.importChanges(schUuid)` raises a confirmation dialog whose button is labelled
「应用修改」 ("Apply changes"), not 「确定」 ("OK").**
A `true` return only means the dialog was raised; nothing has landed on the board. Without clicking that
button nothing happens at all. The same dialog also carries 「取消」 ("Cancel") — do not click that one.

**3. That dialog can take several minutes to render.**
Not seconds — minutes. Any 15- or 40-second watchdog will report "dialog never appeared" and lead you to the
false conclusion that the API does not work. The correct approach is to keep polling for the button with a
timeout of 300 seconds, which is what `sync_pcb_via_importchanges.py` uses by default.

**4. Re-triggering repeatedly dismisses the previous dialog.**
Clicking through a few times while debugging looks like "it stopped raising the dialog", when in fact you
dismissed it yourself. Go slowly, one at a time.

**5. Do not call `openDocument` + `activateDocument` after triggering.**
Re-activating the document while components are being placed interrupts placement and leaves them
half-placed. To watch progress, call bare `pcb_PrimitiveComponent.getAll()` and count — do not touch
document focus.

**6. Click the button through Windows UIAutomation, and do not pass Chinese arguments across processes.**
Passing Chinese text from Python to PowerShell via `subprocess` corrupts it. `click_eda_confirm.ps1`
instead assembles 「应用修改」 from Unicode code points inside the script
(`[char]0x5E94, [char]0x7528, [char]0x4FEE, [char]0x6539`), bypassing every encoding layer. When you do not
know what the button is called, run `list_eda_buttons.ps1` first to dump the current button names.

---

## 3. Connectivity — the most counter-intuitive section

**1. DRC does not check connectivity. This is empirical: break a net deliberately and DRC still reports
zero violations.**
EasyEDA's DRC covers geometric and manufacturing rules such as clearance and hole size only. A clean DRC
therefore says nothing about whether the board is correctly connected. Connectivity must be verified
separately — build an endpoint graph yourself, or use `netcmp_live.py` for a pin-by-pin comparison.

**2. The connectivity engine recognises exactly coincident endpoints only.**
Overlapping track bodies do not connect. T-junctions do not connect. Endpoints that are merely very close
do not connect. The endpoint coordinates of the two segments must be **exactly equal**.
Corollary: never round coordinates to two decimal places — an error of 0.005 is an open circuit, and DRC
will not tell you.

**3. Adjacent collinear same-net segments are merged on creation.**
If you want a junction partway along a trunk and draw it as two segments, the software glues them back into
one track and the junction ends up on a track body (see point 2, where that does not connect).
**The workaround is a zigzag**: place the junction vias alternately 4 mil above and below the trunk
centreline. Adjacent segments then differ in slope and are not merged, while every junction is an endpoint
of some segment. For routing long trunks through the API, this is the approach currently known to work
reliably.

---

## 4. Job boundaries and primitive id lifetime

**1. A `primitiveId` may become invalid once it leaves the current job.**
If you read a batch of ids in job A and pass them to `modify` in job B, the `openDocument` at the start of
job B invalidates all of them. The symptom is `t.isAsync is not a function`, or a batch operation dying
partway through — with everything before that point already written to the board, leaving a net torn in two.

> **Rule: read ids and use ids within the same job.**

**2. A single job has an execution limit of roughly 30 seconds.**
Batch accordingly. Working figures: about 40 property `modify` calls per job, about 150 geometry `modify`
calls per job.

**3. Always pass JS as a file, never as a command-line string.**
`eda_bridge.py run job.js`, not `eda_bridge.py exec "..."`. PowerShell mangles quotes and characters such
as `Ω` beyond recognition.

**4. The bridge service can die, but EasyEDA does not need restarting.**
After `npm run server` is relaunched, the extension on the EasyEDA side reconnects automatically within
about 20 seconds.

**5. The bridge must listen on dual-stack `::`.**
EasyEDA resolves `localhost` to the IPv6 `::1`, so an IPv4-only listener will never be found.

---

## 5. DRC and rules

**1. DRC reports phantom violations.**
Some violations disappear after `closeDocument` and a reopen; they never existed. **Close and reopen the
document, then re-check**, before deciding that a board has failed and needs rework. Phantom violations are
more than enough to make a perfectly sound board look like it needs to be rebuilt from scratch.

**2. After geometry changes, DRC reads a stale cache.**
This is especially true after moving vias through the API. To obtain true values you must **restart
EasyEDA** (launching it with the project path argument). Closing and reopening the document is not enough —
the whole application has to restart.

**3. Clearance rules are split across tables by copper weight.**
A change in layer count can switch which table is in effect, so when calibrating rules, write every table.

**4. Rule table units vary per board.**
Within one project, a newly created board may express `Safe Spacing` entries in mm while an older board uses
mil. Read `entry.unit` and convert before writing rules. Do not assume.

**5. Do not treat copper regions (Copper Region / Filled) as violation targets to fix.**
They are the product of a pour and disappear when it is redone. Including them in a "primitives to fix" list
makes track and via nudging oscillate.

**6. There is no reliable API for repouring copper — only a keystroke.**
`repour_safe.py` activates the target board through the bridge, **then verifies through Win32 that EasyEDA
really is the foreground window**, and only then sends `Shift+B`. If the foreground check fails it aborts —
a keystroke must never land in another application.
Note also that a pass aborted by losing foreground did not pour, and must be retried. An unfinished pour
produces a large crop of spurious "Copper Region" violations that vanish entirely once the pour completes —
so when the violation count jumps unexpectedly, first confirm that the pour actually ran.

---

## 6. Order of geometry operations (clearance remediation)

When the violation count is large, this order gives the best return:

1. **Repour copper first, then count.** Many violations are artefacts of an unfinished pour.
2. **Build a ledger with `neck_analyze.py`.** Statistics by net and by net pair, so you can see which nets
   are actually responsible.
3. **Nudge with `gap_nudge.py`.** Geometry only, no topology change — the safest step. The principle is
   "do not make anything worse": check for space behind a track before moving it, and either distribute the
   move or skip it when there is none.
4. **Reduce width with `width_cut.py`.** Where the over-wide tracks were headroom left during layout rather
   than a current-carrying requirement, reducing the violating tracks to a target width frees clearance.
   Confirm first that the width really is headroom.
5. **Sink to an inner layer with `neck_sink.py`.** When a corridor is genuinely full, move the congested
   trunk segments to an inner layer to free surface clearance. This changes topology — back up first.
6. **Clean up landing points with `fix_sink.py`.** Vias placed during sinking may land too close to the
   board outline or to other holes; this script relocates them.

**Then a judgement call rather than a technical rule:** in congested areas — via traffic jams, dense
bundles — the marginal return of scripting is negative, and adding passes is usually worse than switching to
interactive editing. A workable split is: scripts handle bulk rebuild and verification, a human closes out
the difficult regions.

One more discipline worth stating separately:
**before concluding that a board must be rebuilt, do three things** — check per-branch current, re-check
after clearing phantom violations, and classify the problem as electrical, manufacturability, or rule-based.
Manufacturability problems (a track below the fab's minimum width, a hole below its minimum drill) are fixed
by local adjustment, not by starting over.

---

## 7. Signature traps in specific APIs

- `pcb_PrimitivePolyline.create(net, layer, polygon, lineWidth, primitiveLock)`
  — **`net` comes first** (pass an empty string `""` for a board outline).
  `polygon` must be built with the factory function
  `eda.pcb_MathPolygon.createPolygon(["R", x, y, w, h, 0, 0])`; passing a bare array or plain object raises
  an argument error.
  For a rectangle, `y` denotes the **top edge**, and the vertical extent is `[y-h, y]`.
- `pcb_PrimitiveVia.delete` accepts an array only: `delete([id])`. `pcb_PrimitiveLine.delete` accepts a
  string.
- `pcb_PrimitiveVia.create(net, x, y, holeDiameter, padDiameter)` — the argument order is easy to reverse.
- Do not guess enumeration values. Where the documentation specifies an enum, use the enum member — write
  `EPCB_LayerId.TOP` for a layer argument rather than `1`.
  One note: two geometry scripts in this repository (`neck_sink.py`, `fix_sink.py`) pass raw layer numbers
  (top = 1, inner = 15/16) when assembling JS in bulk, to keep large batches inside a single job. That is
  not the recommended style. Use enums in new code.
- Some enums — the unit enum, for instance — are not reachable in the bridge's eval context. Passing the
  strings `"mm"` / `"mil"` works there instead.

---

## 8. Multi-board projects

**1. Create a new board with `eda.dmt_Board.createBoard()`, no arguments.**
It creates a complete board (schematic, page and PCB included) and returns a board name such as `"Board2"`.
Note that this method lives in the `dmt_Board` namespace, not `dmt_Schematic`.

The sequence is:
`createBoard()` → `dmt_Board.getBoardInfo(boardName)` to obtain `schematic.uuid` and
`schematic.page[0].uuid` → `dmt_EditorControl.openDocument(pageUuid)` for a tabId → `activateDocument(tabId)`.
The page only becomes the active page after activation, and only then does
`modifySchematicName(schUuid, name)` take effect.

**2. Do not use `createSchematic()`.**
With no arguments it creates a detached schematic, after which `getAllSchematicPagesInfo()` and
`getSchematicInfo()` start throwing `reading 'Symbol'` — schematic queries for the whole project are
poisoned. Passing a name does not help either: it treats the name as a board name and returns undefined.

**3. `deleteBoard` removes only the container; it does not cascade to the schematic.**
Call `deleteSchematic(schUuid)` as well for a clean removal.

**4. Count before importing — do not assume a new board is empty.**
A newly created board contains one default placeholder component, so `getAll().length` is 1, not 0.

**5. Different pages of one schematic share a global netlist (same-named nets merge).**
Boards that need independent netlists must therefore be separate boards, not merely separate pages.

---

## 9. Encoding — three unavoidable traps on Chinese Windows

1. **Python crashes when printing Chinese characters or `✓✗`.**
   The console is GBK; a character it cannot encode raises `UnicodeEncodeError` and kills the script.
   Every script should open with `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.
   What makes this trap dangerous is its disguise: the operation itself succeeded, but the script died while
   printing the result, which looks exactly like a failed operation and can send an investigation in
   completely the wrong direction.
2. **Reading PowerShell output requires an explicit encoding.**
   `subprocess.run(..., text=True)` defaults to GBK on Chinese Windows and crashes on the non-GBK bytes in
   「应用修改」. Use `encoding="utf-8", errors="replace"`.
3. **EasyEDA's exported "csv" is really UTF-16LE with tab separators.**
   Parsing it as UTF-8 with commas produces garbage. File contents are also mangled by the stdout encoding
   layer in transit, so convert to base64 on the JS side before returning them (see `export_mfg.py`).

---

## 10. Part numbers and the library

- The netlist-rebuild extension resolves library parts from **`props["Supplier Part"]` (the LCSC C-number)
  only**. `device_name` and footprint name play no part in matching. Without a part number the import fails
  with "no component placed".
- **A wrong part number cannot be repaired afterwards**: `modify` cannot change a component's library
  binding (the property table has no component/symbol/footprint fields at all). The only fix is to correct
  the JSON and re-import. The UI's "component standardisation" does not help either — it standardises to
  whatever the wrong part number points at.
- **Part numbers get discontinued.** When the library returns nothing (both `getByLcscIds` and search come
  back empty), find the current replacement by MPN.
- After a netlist-rebuild import, component SupplierId may be set to the MPN instead of the C-number,
  raising a "supplier mismatch" DRC item. Use `fix_supplier_ids.py` to rewrite them in bulk.
- Component standardisation has no programmatic API — only the UI panel. DRC items likewise cannot be
  retrieved individually, only as a summary.
- For authoritative part data, use `lib_Device.getByLcscIds(["C..."])`: the returned `device.otherProperty`
  carries Supplier Part / Manufacturer / Manufacturer Part, with `manufacturer` and `supplier` at the top
  level. This is more trustworthy than a hand-maintained BOM.

---

## 11. Design discipline for automation scripts

These are not EasyEDA behaviours; they are the ways the scripts driving it tend to go wrong.

1. **Do not hand irreversible actions to a daemon.** A script may observe and flag; deleting, overwriting
   and sending keystrokes should require a human, or several independent confirmations.
2. **An empty set must not evaluate as success.** "All targets complete" must be judged an anomaly, not a
   completion, when the target set is empty.
3. **Look at what you changed.** That is what `render_at.py` is for — take a screenshot and confirm with
   your eyes rather than trusting an API return value.
4. **Back up before changing topology.** `neck_sink.py` saves each net's original geometry to JSON before
   touching it, so a failed net can be restored whole.
5. **Keep a repeatable check at every step.** Run the pin-by-pin netlist comparison
   (`netcmp_live.py` / `compare_netlist.py`) after every geometry pass — it is the only reliable way to tell
   whether a change has broken the netlist.
