English | [简体中文](./netlist-import.zh.md)

# Netlist Rebuild Import: from a netlist to components on the board

This document covers the first half of the chain: **how a netlist becomes a schematic in an EasyEDA project,
and then components placed on a PCB**, without drawing anything by hand.

First, what "netlist rebuild" refers to: an official extension in the EasyEDA Pro extension marketplace
(`eext-generate-schematic-from-netlist`) that accepts a JSON file in a specific format and generates a
schematic from the components and connections it describes. The first stage below is about feeding it.

---

## Overview

```
.tel netlist + BOM (with LCSC part numbers)
        │  tel2json_netlist.py
        ▼
   netlist .json with part numbers  ──── netlist_drc.py (offline check, catches the obvious errors)
        │
        ├─(route A) manual import through the "netlist rebuild" extension
        └─(route B) generate_schematic_from_json.py, fully automated through the bridge
        ▼
   schematic populated
        │  fix_supplier_ids.py  rewrite SupplierId
        │  fix_nc.py            mark unused pins as NC
        ▼
   schematic DRC clean
        │  10_export_netlist.js + compare_netlist.py  pin-by-pin import fidelity
        ▼
   import confirmed faithful
        │  sync_pcb_via_importchanges.py
        ▼
   components and ratlines on the PCB
```

---

## Step 0: why LCSC part numbers are mandatory

This is the crux of the whole thing, stated first to save you from repeated collisions later.

**The netlist-rebuild extension looks at exactly one field when resolving library parts:
`props["Supplier Part"]`, the LCSC C-number.** It passes that number to
`eda.lib_Device.getByLcscIds()` to fetch the part and place it. `device_name` (the manufacturer part
number) and `Footprint` (the package name) **play no role in matching whatsoever**.

Consequently:

- No part number → the import fails outright with "no component placed".
- Wrong part number → a component is placed, but the wrong one (wrong package, wrong symbol), **and it
  cannot be corrected afterwards**. `modify` cannot change a component's library binding; the property
  table has no component / symbol / footprint fields at all. The only fix is to correct the JSON and
  re-import.
- The UI's "component standardisation" does not rescue a wrong part number either — it will simply
  standardise to whatever that wrong number points at.

The conclusion: **part numbers have to be right at the moment the JSON is generated.** There is no recovery
window later. The [component sourcing guide](./component-sourcing.en.md) covers how to get them right.

Part numbers also get discontinued. When `getByLcscIds` and search both return empty, the number is no
longer in the library; find the current replacement by MPN on the supplier's site.

---

## Step 1: `.tel` + BOM → netlist JSON with part numbers

```bash
python tools/tel2json_netlist.py in.tel out.json --bom bom.csv [--override over.json]
```

`.tel` is a netlist format EasyEDA Pro can export itself, structured as `$PACKAGES` (components and
footprints) and `$NETS` (nets and pins). The BOM supplies part numbers. The script matches the two by
designator.

**Part number matching has three fallback levels**, because real BOMs are never tidy:

1. **Exact designator.** Parses the BOM's Designator column, supporting comma lists and ranges such as
   `R01-R08` (same prefix, consecutive numbers). Rows containing an ellipsis `...` are skipped — an
   ellipsis cannot be expanded reliably, and expanding it anyway is guesswork.
2. **Footprint + value.** Matches on (footprint type, value token). This level covers BOMs with incomplete
   designator lists. Footprint types are normalised first: `C0402` / `R0402` / `0402` all collapse to
   `0402`, and FPC connectors collapse by pin count to forms like `FPC-8P`.
3. **Unique footprint.** If a footprint type maps to exactly one part number across the whole BOM, use it.

Components that fail all three levels are **listed as warnings; the script never silently fills in a wrong
part number** — that is a hard design requirement. Resolve the warnings with `--override`, a
`{designator: part number}` JSON file that takes the highest priority. Connectors need overrides most
often, because footprint names in the BOM and in the `.tel` frequently disagree.

The output looks like this (which is also `examples/example_netlist.json`):

```json
{
  "gge1": {
    "props": { "Designator": "R1", "device_name": "...", "value": "10k", "Supplier Part": "C0000001" },
    "pins":  { "1": "VCC_3V3", "2": "SENSE_A" }
  }
}
```

Two format details that will break the import if you get them wrong: component keys must be `gge1` /
`gge2` numbered in sequence, and the `props` field names `device_name` and `value` are lower-case.

---

## Step 2: offline check

```bash
python tools/netlist_drc.py out.json [other-board.json ...]
```

Run this **before** importing into EasyEDA; it needs no running application. It checks three things:

- **Single-pin nets** — a net with only one pin attached is almost always a drawing or omission error, and
  importing it achieves nothing.
- **Duplicate designators** — the same designator appearing twice.
- **Pin connection rate** — how many of the total pins are connected, so you have a figure to sanity-check.

The step is cheap and heads off most of the "only discovered the miswiring after importing" rework.

**What it cannot catch:** wrong connections caused by same-name net merging. Only the pin-by-pin comparison
in step 5 finds that class — see the failure mode described there.

---

## Step 3: generate the schematic

Two routes; pick one.

### Route A: manual import through the official "netlist rebuild" extension

Install the extension in EasyEDA (search the marketplace for
`eext-generate-schematic-from-netlist`) and feed it the JSON from the previous step. On success it reports
"Import netlist success".

Reliable, but it needs a human to click.

### Route B: `generate_schematic_from_json.py`, fully automated through the bridge

```bash
python tools/generate_schematic_from_json.py out.json [--clear] [--batch 10] [--test 5]
```

This bypasses the extension and builds the schematic through the API one component at a time: grid layout →
`lib_Device.getByLcscIds(part number)` per component to fetch it from the library (cached) →
`sch_PrimitiveComponent.create` to place it → `modify` to set the designator → a short net-carrying wire
from each pin (same-named nets are then logically connected).

`--test N` places a handful of components first, so you can confirm that part numbers resolve and
designators are set correctly before running the full set. `--clear` empties the current schematic first —
a newly created board contains a default placeholder component that will otherwise be mixed in.

**One argument here has to be remembered.** The full signature of `create` is:

```js
create(component, x, y, subPartName, rotation, mirror, addIntoBom, addIntoPcb)
```

Omit the last two arguments — `addIntoPcb` in particular — and the components live only in the schematic,
so **step 6 will place zero components on the PCB**. This script passes `true` by default. If you have an
inherited board whose components will not reach the PCB, repair them per component with
`sch_PrimitiveComponent.modify(id, {addIntoPcb: true, addIntoBom: true})` followed by `sch_Document.save()`.

Do not raise the batch size too far: a single bridge job times out after roughly 30 seconds.

---

## Step 4: clear the schematic DRC

```bash
python tools/fix_supplier_ids.py out.json [batch size]
python tools/fix_nc.py out.json [batch size]
```

- `fix_supplier_ids.py` — after a netlist-rebuild import, component SupplierId is often set to the MPN
  rather than the C-number, which raises a "supplier mismatch" DRC item. This script rewrites it in bulk,
  by designator.
- `fix_nc.py` — unused pins raise "floating pin, consider placing a no-connect marker". This script reads
  which pins each component actually uses from the netlist and marks the rest with
  `setState_NoConnected(true).done()`.

Both run in batches to stay under the 30-second limit.

---

## Step 5: pin-by-pin comparison to confirm import fidelity

Do not skip this step.

```bash
# first export the resulting netlist through the bridge
# (edit the board name and path in examples/10_export_netlist.js)
python tools/eda_bridge.py run examples/10_export_netlist.js
# then compare
python tools/compare_netlist.py out.json C:/tmp/board_export.json
```

This diffs the source netlist against the netlist EasyEDA produces, checking for missing components and for
the net on every pin. The target is **zero discrepancies**.

**The class of error this catches and ERC does not: short stubs crossing a neighbouring pin and merging
nets.**

On components with closely spaced pins — a two-pin screw terminal whose pins are only 10 units apart, for
example — giving every pin a horizontal stub of length +20 makes those stubs **cross each other's pin**,
merging two nets that were meant to stay separate.

Schematic ERC reports zero for this and shows nothing unusual. Only the pin-by-pin comparison finds it.

The fix: delete the crossing stubs (`sch_PrimitiveWire.delete`) and redraw them **vertically offset**
(`create([x, y, x, y±60], net)`), then re-export and re-compare to confirm it returns to zero.

Ordinary resistors and capacitors are unaffected — their pin pitch is around 100, so a stub of 20 cannot
reach. **Any component whose pin pitch is smaller than the stub length needs watching.**

EasyEDA also provides `SYS_Tool.netlistComparison` for verifying import fidelity, so the two routes can
cross-check each other.

---

## Step 6: sync to the PCB

```bash
python tools/sync_pcb_via_importchanges.py <BoardName> [wait seconds, default 300]
```

This step has the highest density of traps; section 2 of [pitfalls](./pitfalls.en.md) is devoted to it.
Only the three most damaging are repeated here:

1. **`importChanges` returning `true` does not mean components landed on the board.** It only raised a
   confirmation dialog. Components are placed only when the button labelled 「应用修改」 ("Apply changes",
   not 「确定」/"OK") is clicked.
2. **That dialog can take several minutes to render.** A 15- or 40-second watchdog will necessarily report
   "dialog never appeared" and lead you to conclude the API is broken. The default wait is 300 seconds.
3. **Do not re-activate the document after triggering.** Calling `openDocument` + `activateDocument` during
   placement interrupts it and leaves components half-placed. To watch progress, call bare `getAll()` and
   count.

What the script does: fetch board info → activate the PCB once → record the pre-import component count →
trigger `importChanges` → call `click_eda_confirm.ps1` to find and click 「应用修改」 through UIAutomation →
poll bare `getAll()` until the count stabilises.

When the button cannot be found, run the diagnostic first:

```powershell
powershell -ExecutionPolicy Bypass -File tools/list_eda_buttons.ps1
```

It dumps every button name in every EasyEDA window. Button labels change between versions — find the real
name, then adjust the script.

---

## Step 7: what comes next

At this point the PCB carries components and ratlines. Layout and routing are a separate topic:

- Placement, board outline, routing: `setState_X/Y/Rotation` on `pcb_PrimitiveComponent`,
  `pcb_PrimitivePolyline.create`, `pcb_PrimitiveLine.create`.
- Autorouting: export with `getDsnFile` → FreeRouting → import back with `importAutoRouteSesFile`.
  (FreeRouting 1.9 works in batch mode; 2.2.4 has a fatal null-pointer issue.)
- Clearance remediation: repour copper with `repour_safe` first, then `neck_analyze` → `gap_nudge` →
  `width_cut` → `neck_sink` → `fix_sink`. The order and the reasoning behind it are in section 6 of
  [pitfalls](./pitfalls.en.md).
- Verification: `netcmp_live.py` for pin-by-pin regression, `render_at.py` for a screenshot to check by eye.
- Manufacturing files: `export_mfg.py` for BOM and pick-and-place.

One closing reminder, which also appears in [pitfalls](./pitfalls.en.md) and is worth stating twice:
**a clean DRC does not mean a correctly connected board. DRC does not check connectivity — break a net
deliberately and it still reports zero.** Connectivity must be verified separately.
