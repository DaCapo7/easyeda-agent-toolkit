English | [简体中文](./i18n/zh-Hans/)

# easyeda-agent-toolkit

**An automation toolkit and field guide for driving EasyEDA Pro (嘉立创EDA专业版) from an AI coding agent, built on the official easyeda-api-skill bridge.**

A set of Python and PowerShell scripts that let an AI coding agent such as Claude Code operate EasyEDA Pro
end to end: convert a netlist, generate a schematic, sync it to the PCB, run DRC, batch-adjust track widths
and geometry, and export manufacturing files. A few operations genuinely cannot be reached through the API;
those are called out explicitly in the docs, along with the UI-automation workarounds this toolkit uses.

The chain starts one step earlier than the scripts do. `prompts/` holds **AI-agnostic templates** for the
component sourcing stage — turning circuit requirements into a BOM with verified supplier part numbers —
so that stage has the same evidence discipline as the automated steps that follow.

> **Documentation language.** Every guide under `docs/` and every template under `prompts/` ships in
> both English and Chinese, distinguished by an `.en.md` / `.zh.md` suffix. This README is available in
> [Chinese](./i18n/zh-Hans/) as well. Script docstrings and console output remain Chinese.

---

## Contents

- [Scope](#scope)
- [Relationship to the official easyeda-api-skill](#relationship-to-the-official-easyeda-api-skill)
- [Setup](#setup)
- [First commands](#first-commands)
- [Component sourcing](#component-sourcing)
- [Workflow: from netlist to manufacturing files](#workflow-from-netlist-to-manufacturing-files)
- [Tool reference](#tool-reference)
- [Pitfalls worth reading first](#pitfalls-worth-reading-first)
- [Repository layout](#repository-layout)
- [Disclaimer](#disclaimer)

---

## Scope

**What this is.** Scripts that let an AI agent perform repetitive EasyEDA Pro work — bulk property edits,
bulk geometry moves, bulk verification, file export — plus a written record of API behaviours that are not
covered by the official documentation.

**What this is not.** Not an autorouter, and not a "describe a board and get a board" system. Decisions that
need engineering judgement — how to close out a congested region, how to lay out the board outline, which
layer a given net belongs on — remain faster to make by hand. In congested areas the marginal return of
running more script passes turns negative; interactive editing is usually the quicker path there. The
practical split is: scripts handle bulk rebuild and verification, a human handles the hard regions.

**Why the docs matter.** Several EasyEDA Pro API behaviours are counter-intuitive: property writes that
report success but revert on restart, a DRC that does not check connectivity at all, a confirmation dialog
that can take minutes to render, and collinear same-net segments that get merged on creation. These are not
in the official reference. [`docs/pitfalls.en.md`](docs/pitfalls.en.md) collects them; the
[pitfalls section](#pitfalls-worth-reading-first) below summarises the ones most likely to cost you a day.

---

## Relationship to the official easyeda-api-skill

```
   AI agent                this repo                official easyeda-api-skill        EasyEDA Pro
 (Claude Code, ...)      (Python / PS)                 (Node bridge server)      (run-api-gateway ext.)
       │                      │                              │                            │
       │  compose a JS job    │                              │                            │
       ├─────────────────────>│                              │                            │
       │                      │  HTTP POST /execute          │                            │
       │                      ├─────────────────────────────>│                            │
       │                      │                              │   JS over WebSocket        │
       │                      │                              ├───────────────────────────>│
       │                      │                              │                            │ eda.* API
       │                      │                              │<───────────────────────────┤
       │                      │<─────────────────────────────┤        result              │
       │<─────────────────────┤  parse / verify / next pass  │                            │
```

**The Node bridge in the middle is official EasyEDA software, not part of this repository.** It comes from
[easyeda/easyeda-api-skill](https://github.com/easyeda/easyeda-api-skill) (JLCEDA, MIT). This repository
contains none of its code — install it separately, as described under [Setup](#setup).

What this repository adds on top:

- `tools/eda_bridge.py` is an HTTP client for the bridge: it scans ports 49620–49629, reports connection
  status, submits a `.js` file as a job, and returns the JSON result. Every online script goes through it.
  (`tel2json_netlist.py`, `netlist_drc.py` and `compare_netlist.py` are fully offline and need no running
  EasyEDA instance.)
- The remaining scripts are job generators and result verifiers: they assemble a JS snippet, send it through
  `eda_bridge.py`, then do the geometry, comparison and decision work in Python before generating the next
  snippet. Heavy computation — clearance checks, path planning, pin-by-pin netlist comparison — stays on the
  Python side; EasyEDA only reads and writes primitives.
- Two PowerShell scripts use a different channel entirely: Windows UIAutomation, to click buttons in the
  EasyEDA UI. Some actions have no API equivalent — most importantly the confirmation dialog raised by
  `importChanges`, which the API can open but cannot dismiss.

In short: the official skill determines whether JS can reach EasyEDA; this repository determines what JS to
send and how to confirm it actually took effect.

---

## Setup

### 1. EasyEDA Pro desktop client

Every script here was validated against the **desktop client**. The two PowerShell scripts use Windows
UIAutomation and therefore require Windows.

### 2. Install the run-api-gateway extension

Extension page: <https://ext.lceda.cn/item/oshwhub/run-api-gateway>

Make sure it is enabled. This extension is what connects EasyEDA to the bridge.

### 3. Install the official easyeda-api-skill and start the bridge

```bash
git clone https://github.com/easyeda/easyeda-api-skill.git
cd easyeda-api-skill
npm install
npm run server        # binds the first free port in 49620-49629
```

Follow the official README for the authoritative steps — npm script names differ between versions, and some
versions require `npm run build:docs` first.

If you use Claude Code or another tool that supports the Agent Skills standard, put that directory somewhere
the tool can read. The agent will pick up its `SKILL.md` and get the full API reference. **This repository
deliberately does not duplicate the official API documentation — look API calls up there.**

### 4. Clone this repository

```bash
git clone https://github.com/DaCapo7/easyeda-agent-toolkit.git
cd easyeda-agent-toolkit
```

Requires Python 3.8+ and **no third-party packages** — standard library only.

For a one-click bridge launch, set `SKILL_DIR` inside `tools/start_bridge.bat` to your local
easyeda-api-skill path and run it.

---

## First commands

**1. Confirm the bridge is reachable:**

```bash
python tools/eda_bridge.py health
```

Expected:

```
[Bridge] 端口 49620  status=ok  窗口数=1
[嘉立创] 已连接  活动窗口=xxxx
```

`未找到 Bridge` ("bridge not found") means `npm run server` is not running. `嘉立创未连接`
("EasyEDA not connected") means the extension is not installed or not enabled.

> The bridge must listen on dual-stack `::`. EasyEDA resolves `localhost` to the IPv6 `::1`, so an
> IPv4-only listener will never be found.

**2. Run the first job:**

```bash
python tools/eda_bridge.py run examples/00_probe.js
```

This lists every board in the current project with its uuid. **Note the `parentBoardName` values** — almost
every script in this repository takes one as its first argument.

**3. If several EasyEDA windows are open:**

```bash
python tools/eda_bridge.py windows            # list connected windows
python tools/eda_bridge.py select <windowId>  # choose the active one
```

> **Always pass JS as a file (`run <file>`), never as a command-line string (`exec "<string>"`).**
> PowerShell mangles quotes and characters such as `Ω`.

**4. Offline check — no EasyEDA required.** The repository ships a four-component demo netlist, so you can
exercise the netlist stage immediately:

```bash
python tools/tel2json_netlist.py examples/demo.tel examples/out.json --bom examples/demo_bom.csv
python tools/netlist_drc.py examples/out.json
```

The first command reports `器件 4 | 引脚 10 | 已配料号 4/4` (4 components, 10 pins, 4/4 part numbers
resolved). The second flags `NC_SPARE` as a net with only one pin attached, which is exactly what it is for.

---

## Component sourcing

The chain begins before any script runs: circuit requirements have to become a BOM carrying real supplier
part numbers. That stage is research, not automation, so this repository supplies **prompt templates**
rather than code. Hand a template to any AI with web search, and finish with a verification checklist.

The templates name no AI product, assume no knowledge of your project, and mark every blank with
〈angle-bracket〉 placeholders. They work the same whichever model picks them up.

| Template | Purpose |
|---|---|
| [`prompts/component-sourcing-brief.en.md`](prompts/component-sourcing-brief.en.md) | Sourcing brief: you fill in the requirements (electrical, package, temperature, cost ceiling, assembly constraints, target assembly service, supply), the AI returns a primary choice and alternates compared line by line |
| [`prompts/part-number-verification.en.md`](prompts/part-number-verification.en.md) | Verification checklist run before anything is written into the BOM |

Chinese versions: `component-sourcing-brief.zh.md`, `part-number-verification.zh.md`. The guide
[`docs/component-sourcing.en.md`](docs/component-sourcing.en.md) covers the stage and its handoff contract.

**The rule that matters most:** a C-number counts only after it has actually been retrieved from the
component library — the search returned that part, stock is above zero, and package and key parameters match
item by item. Part numbers are a category where language models fail quietly: the format is regular and the
length fixed, so a well-formed number that does not exist, or that denotes something entirely different, is
easy to emit and shows no symptom until import.

Verification runs through either the LCSC/JLCPCB web library, or through the bridge against the library the
EasyEDA client is actually connected to — `examples/30_library_search.js` wraps
`eda.lib_Device.search()` and `eda.lib_Device.getByLcscIds()` for that purpose, and reports stock, price and
basic/extended library membership.

Why this belongs in the repository: every automated step downstream assumes `Supplier Part` is correct. If
it is not, `tel2json_netlist.py` faithfully writes the wrong number into the netlist, the import faithfully
places the wrong component, and `fix_supplier_ids.py` faithfully makes the wrong number more consistent. No
later step ever reports that the number itself was wrong.

---

## Workflow: from netlist to manufacturing files

The full write-up is in [`docs/netlist-import.en.md`](docs/netlist-import.en.md). The skeleton:

```
circuit requirements
        │  prompts/component-sourcing-brief.en.md   (sourcing research)
        │  prompts/part-number-verification.en.md   (before writing the BOM)
        ▼
.tel netlist + BOM (with verified LCSC part numbers)
        │  tel2json_netlist.py
        ▼
   netlist .json with part numbers  ──── netlist_drc.py  (offline sanity check)
        │  generate_schematic_from_json.py
        ▼
   schematic populated
        │  fix_supplier_ids.py / fix_nc.py
        ▼
   schematic DRC clean
        │  compare_netlist.py  (pin-by-pin import fidelity)
        ▼
        │  sync_pcb_via_importchanges.py
        ▼
   components and ratlines on the PCB
        │  placement / outline / routing (API or FreeRouting)
        ▼
        │  repour_safe → neck_analyze → gap_nudge → width_cut → neck_sink → fix_sink
        ▼
   DRC converged
        │  netcmp_live.py pin-by-pin regression + render_at.py visual check
        ▼
        │  export_mfg.py
        ▼
   BOM + pick-and-place, ready to order
```

### Critical point 1: part numbers

The netlist-rebuild extension resolves library parts **solely from `props["Supplier Part"]`, the LCSC
C-number**. Manufacturer part number and footprint name play no role in matching. A missing part number
fails the import outright; a *wrong* part number silently places the wrong component, **and it cannot be
corrected afterwards** — `modify` cannot change a component's library binding, so the only fix is to correct
the JSON and re-import. The "component standardisation" panel in the UI does not help either; it will simply
standardise to whatever the wrong part number points at.

Accordingly, `tel2json_netlist.py` resolves part numbers through three fallback levels (exact designator →
footprint + value → unique footprint) and **warns about anything it cannot resolve rather than guessing**.

### Critical point 2: `addIntoPcb`

```js
sch_PrimitiveComponent.create(component, x, y, subPartName, rotation, mirror, addIntoBom, addIntoPcb)
```

Omit the last two arguments — `addIntoPcb` in particular — and the components exist only in the schematic.
The subsequent sync to PCB then places **zero components**, with no error to explain why.

### Critical point 3: the dialog that takes minutes

`pcb_Document.importChanges(schUuid)` returning `true` **does not mean components landed on the board**. It
means a confirmation dialog was raised. Components are placed only when the button labelled **「应用修改」**
("Apply changes" — *not* 「确定」/"OK") is clicked.

On some versions that dialog takes **several minutes** to render. A 15- or 40-second watchdog will report
"dialog never appeared" and lead you to conclude the API is broken.

`sync_pcb_via_importchanges.py` waits 300 seconds by default, scanning for the button throughout. If the
button is not found, run `list_eda_buttons.ps1` to dump the button names actually present.

### Critical point 4: a clean DRC does not mean a connected board

**Empirically: break a net deliberately and DRC still reports zero violations.** EasyEDA's DRC covers
clearance and hole geometry; it does **not** check connectivity.

The connectivity engine also recognises **exactly coincident endpoints only** — overlapping track bodies do
not connect, T-junctions do not connect, and endpoints that are merely very close do not connect. Rounding
coordinates to two decimal places produces an open circuit, silently.

Run `netcmp_live.py` as a pin-by-pin regression after every geometry pass.

### Critical point 5: writes that report success but do not persist

Some API calls **return success, read back the new value immediately, and still hold the old value after a
restart**. Confirmed cases: via hole/pad diameter, copper-pour outline width, and rule configuration passed
in the wrong shape.

> **Reading the new value back is not verification. After changing a critical property, restart EasyEDA and
> read it again.**

---

## Tool reference

Everything lives in `tools/`, flat — the scripts call each other by same-directory relative path, so keep
them together.

### Bridge and UI

| Script | Purpose |
|---|---|
| `eda_bridge.py` | Entry point for every online script. Finds the bridge, reports status, submits `.js` jobs. Subcommands: `health` / `windows` / `select` / `run` / `exec` |
| `start_bridge.bat` | Starts the official bridge and checks the connection (set `SKILL_DIR` first) |
| `click_eda_confirm.ps1` | Clicks 「应用修改」 via UIAutomation. The Chinese button name is assembled from Unicode code points inside the script, bypassing every encoding layer |
| `list_eda_buttons.ps1` | Diagnostic: dumps every button name in every EasyEDA window. Use it when a version changes the button text |

### Netlist to schematic

| Script | Purpose |
|---|---|
| `tel2json_netlist.py` | `.tel` + BOM → netlist JSON with part numbers. Three-level matching; warns instead of guessing |
| `netlist_drc.py` | Offline check: single-pin nets, duplicate designators, connection rate. **No EasyEDA needed** |
| `generate_schematic_from_json.py` | Builds the schematic through the bridge: library lookup → place → rename → short net-carrying wire per pin |
| `fix_supplier_ids.py` | Bulk-corrects SupplierId, clearing the "supplier mismatch" DRC item |
| `fix_nc.py` | Bulk-marks unused pins as NC, clearing the "floating pin" warning |
| `compare_netlist.py` | Pin-by-pin diff of source netlist against the exported result, to verify import fidelity |
| `netcmp_live.py` | Reads live board state and diffs it against the `.tel` source. Use as regression after geometry work |

### Schematic to PCB

| Script | Purpose |
|---|---|
| `sync_pcb_via_importchanges.py` | `importChanges` + automatic 「应用修改」 click + polling until the count stabilises. 300 s dialog timeout by default |

### PCB geometry

Run in this order:

| Script | Purpose |
|---|---|
| `repour_safe.py` | Safe copper repour. Verifies EasyEDA is actually the foreground window before sending `Shift+B`, and aborts otherwise — keystrokes must never land in another application |
| `neck_analyze.py` | Violation ledger by net and by net pair, so you can see which nets are responsible |
| `gap_nudge.py` | Translates violating tracks. Geometry only, no topology change; endpoints move together with segments sharing them exactly; checks for space before moving |
| `width_cut.py` | Reduces over-wide violating tracks to a target width. Effective where the extra width was headroom rather than a current-carrying requirement |
| `neck_sink.py` | Moves congested trunk segments to an inner layer to free surface clearance. Changes topology; backs up each net before touching it |
| `fix_sink.py` | Relocates vias placed too close to the board outline or to other holes |
| `render_at.py` | Screenshot of a point of interest. **Look at what you changed** — do not trust API return values alone |

### Manufacturing

| Script | Purpose |
|---|---|
| `export_mfg.py` | Exports BOM and pick-and-place. Handles two traps: EasyEDA's "csv" is really UTF-16LE with tab separators, and file contents are base64-encoded across the bridge to survive console encoding |

---

## Pitfalls worth reading first

Full list in [`docs/pitfalls.en.md`](docs/pitfalls.en.md). The ten most expensive:

1. **Writes that do not persist.** Via diameter and pour outline width both report success without being
   saved. Restart EasyEDA to verify.
2. **DRC ignores connectivity.** A broken net still reports zero. Verify connectivity separately.
3. **Connectivity requires exactly coincident endpoints.** Rounded coordinates mean an open circuit, with no
   warning.
4. **Collinear same-net segments merge on creation.** To keep a junction mid-trunk, offset the junction vias
   a few mil alternately above and below the trunk centreline, so adjacent segments differ in slope and are
   not merged. Otherwise the split segments are glued back into one and the junction lands on a track body
   (see point 3).
5. **Primitive ids do not survive a job boundary.** Read ids and use them within the same bridge job. Using
   them across jobs throws `t.isAsync is not a function` and can kill a batch halfway — with everything
   before that point already written, leaving a net torn in two.
6. **DRC reports phantom violations.** They disappear after `closeDocument` and reopen. Re-check before
   concluding a board needs rework.
7. **Three encoding traps on Chinese Windows.** Python crashes printing non-GBK characters (use
   `sys.stdout.reconfigure`); reading PowerShell output requires an explicit utf-8 encoding; EasyEDA's
   exported "csv" is UTF-16LE with tabs. A script that crashes while printing its own success message looks
   exactly like a failure.
8. **`pcb_PrimitivePolyline.create(net, layer, polygon, lineWidth, primitiveLock)`** — `net` comes first,
   and `polygon` must be built with the `pcb_MathPolygon.createPolygon([...])` factory. Passing a bare array
   raises an argument error.
9. **Roughly 30 s per job.** Batch accordingly: about 40 property `modify` calls, or about 150 geometry
   `modify` calls, per job.
10. **Before declaring a board unusable**, do three things: check per-branch current, re-check after
    clearing phantom violations, and separate electrical problems from manufacturability problems from rule
    problems. Manufacturability problems — a track below the fab's minimum width, a hole below its minimum
    drill — are fixed by local adjustment, not by starting over.

---

## Repository layout

```
easyeda-agent-toolkit/
├── README.md                 this file (English)
├── i18n/zh-Hans/README.md    Chinese version
├── LICENSE                   MIT
├── docs/                     guides, English and Chinese
│   ├── component-sourcing.{en,zh}.md   sourcing stage and its handoff contract
│   ├── netlist-import.{en,zh}.md       full netlist-to-PCB walkthrough
│   └── pitfalls.{en,zh}.md             API behaviours and pitfalls
├── prompts/                  AI-agnostic templates, English and Chinese
│   ├── component-sourcing-brief.{en,zh}.md
│   └── part-number-verification.{en,zh}.md
├── tools/                    scripts (flat; they call each other by relative path)
│   └── eda_jobs/             generated temporary JS jobs land here (not tracked)
└── examples/
    ├── 00_probe.js            connectivity probe and board listing
    ├── 10_export_netlist.js   export the resulting netlist to disk
    ├── 20_pin_truth_probe.js  pin-number probe (more reliable than a datasheet)
    ├── 30_library_search.js   library search and part-number verification
    ├── demo.tel               demo netlist, four components, runnable as-is
    ├── demo_bom.csv           matching BOM
    └── example_netlist.json   the output of that demo, and the JSON format reference
```

Part numbers and net names under `examples/` are placeholders and correspond to no real design.

---

## Disclaimer

**This is an unofficial project with no affiliation to JLC / LCEDA / EasyEDA**, and no endorsement from
them. Product names and trademarks are used only to describe compatibility.

**Official skill.** This repository depends on
[easyeda/easyeda-api-skill](https://github.com/easyeda/easyeda-api-skill) (JLCEDA, MIT) for its bridge
server and API reference, but **contains, copies and redistributes none of it**. Install it separately as
described under [Setup](#setup). Its copyright belongs to JLCEDA.

**Authorship.** These scripts were produced by Claude (Anthropic) in collaboration with the author. This
repository is released under the MIT licence.

**Use at your own risk.** These scripts **modify your EasyEDA project files directly**, and several of them
(`neck_sink.py`, `fix_sink.py`, `width_cut.py`, `gap_nudge.py`) change board geometry in bulk. **Back up
your project first.** The author accepts no liability for design loss, production loss or cost arising from
use of this toolkit. Specific behaviours — button labels, API signatures, DRC response shapes — change
between EasyEDA versions; try them on a scrap board first.

**Data.** This repository contains no credentials, no API tokens and no private board data — no netlists,
coordinates, part numbers, net names or Gerbers. Everything under `examples/` is fabricated.
