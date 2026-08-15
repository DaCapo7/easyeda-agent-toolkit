# Part Number Verification Checklist (template)

How to use: work through this checklist after sourcing research produces candidates and before any part
number is written into the BOM. The template targets no particular AI product. The executor can be a human
or an AI.

---

## Why verification is mandatory

The netlist import resolves library parts from `Supplier Part` (the LCSC C-number). That field has three
properties:

1. **It is the only field that matches.** Manufacturer part number and package name play no role. A wrong
   number places a wrong component.
2. **It cannot be corrected afterwards.** `modify` cannot change a component's library binding; the only
   fix is to correct the netlist JSON and re-import. The "component standardisation" panel does not help
   either — it standardises to whatever the wrong number points at.
3. **Numbers get discontinued.** A number that worked once may later return nothing from the library.

This step therefore has to be right before the BOM is written. There is no recovery window later.

---

## Hard rule

> **A C-number counts only after it has actually been retrieved from the component library.**
>
> "Retrieved" means all three of the following hold:
> **(1) the search actually returned a part for that number; (2) stock > 0; (3) package and key parameters
> match the specification item by item.**
>
> **Never produce a number from memory, impression, or because it "looks right".** Language models are
> notably unreliable with component part numbers: the format is regular and the length is fixed, which makes
> it easy to emit a number that is perfectly well-formed but does not exist — or exists and denotes something
> entirely different. Neither failure shows any symptom before import.
>
> Any number that has not actually been searched must be labelled "unverified" and kept out of the BOM.

---

## Verification channels

Either channel is sufficient. Using both is safer.

### Channel A: web library search

Search by part number or MPN in the LCSC / JLCPCB parts library web interface.

Record: number, MPN, package, key parameters, stock, price, library membership (basic / extended), and the
time you read them.

This channel needs no setup and is available to anyone.

### Channel B: query the library through the bridge, inside EasyEDA

If the official easyeda-api-skill bridge and the run-api-gateway extension are already installed per the
repository README, you can query the component library that the EasyEDA client is connected to. The
advantage: **you are searching the same library the import will use**, so there is no "present on the
website, absent in the client library" discrepancy.

`examples/30_library_search.js` in this repository does exactly this:

```bash
# edit KEY (search term) or LCSC_IDS (numbers to verify) in the script, then
python tools/eda_bridge.py run examples/30_library_search.js
```

It wraps two API calls, with signatures taken from the `LIB_Device` reference in the official
easyeda-api-skill:

```js
// keyword search, returns a candidate list
eda.lib_Device.search(key, libraryUuid?, classification?, symbolType?, itemsOfPage?, page?)

// exact lookup by C-number; an empty result means the number does not exist in the library
eda.lib_Device.getByLcscIds(lcscIds, libraryUuid?, allowMultiMatch?)
```

Search results expose manufacturer, MPN, supplier part number, package, stock, price, and library
membership (`"standard"` = basic library, `"extend"` = extended library).

> **A note on where the fields live.** In the official reference the commercial fields (stock, price,
> library category, supplier number, manufacturer) are marked obsolete at the top level and documented as
> moved into `otherProperty`. The top-level fields may still be present, or may be empty. For that reason
> `30_library_search.js` prints both the **raw key names** found in `otherProperty` and a normalised view —
> check what your version actually returns before writing a parser, rather than copying field names from
> elsewhere.

---

## Checklist

Tick every item for each number destined for the BOM. Any failure disqualifies the number.

### 1. Existence

- [ ] The number was **actually retrieved** from the library (not from impression, not copied from elsewhere)
- [ ] The returned name/description matches the expected component class (do not accept a capacitor when
      searching for a resistor)
- [ ] Retrieval time and channel recorded

### 2. Stock

- [ ] Stock > 0
- [ ] Stock ≥ required quantity, with margin for setup loss, rework, and a second build
- [ ] Stock figure recorded with its timestamp — an untimed stock number is meaningless

### 3. Package

- [ ] The library package name matches the package named in the BOM and netlist
- [ ] Physical dimensions fit the space allocated on the board
- [ ] Pin count and pin pitch match the schematic symbol
- [ ] Through-hole versus SMD confirmed — through-hole parts need separate hand-soldering on an SMT-only
      line and must be flagged in advance

### 4. Parameters

Compare against the sourcing specification item by item, not by overall impression:

- [ ] Key parameter 1: 〈required〉 vs 〈actual〉
- [ ] Key parameter 2: 〈required〉 vs 〈actual〉
- [ ] Key parameter 3: 〈required〉 vs 〈actual〉
- [ ] Operating temperature range covers the operating conditions
- [ ] Tolerance / accuracy meets the requirement
- [ ] Parameters sourced from the manufacturer datasheet, with revision or date recorded

### 5. Commercial and process

- [ ] Library membership confirmed (basic / extended); setup-fee impact assessed for extended parts
- [ ] Unit price within budget, with the corresponding volume stated
- [ ] Lifecycle status healthy (not NRND or EOL)
- [ ] MPN recorded — it is how you find a current replacement when the number is discontinued

### 6. Consistency

- [ ] `Supplier Part` in the BOM matches the verified number **character for character**
- [ ] `Manufacturer Part` in the BOM matches the library MPN
- [ ] `Footprint` in the BOM matches the library package
- [ ] The same component uses the same number across every board and every BOM row

---

## Output format

```
Verified at:      〈YYYY-MM-DD HH:MM〉
Channel:          〈web search / bridge query / both〉

| Designator | Supplier part | MPN | Package | Stock | Library | Parameters | Verdict |
|---|---|---|---|---|---|---|---|
| 〈R1〉 | 〈fill from the actual search result — e.g. a generic 0402 10 kΩ resistor〉 | | | | | all match | pass |

Failed:
- 〈number〉: 〈which item failed, by how much, what to do〉

Unverified:
- 〈number〉: 〈why it was not verified, what is missing〉
```

The "Unverified" section may be empty, but must not be omitted — it is the honesty checkpoint of this
checklist.

---

## Post-import cross-checks

After the numbers are in the BOM and the netlist has been imported, two automated checks in this repository
apply:

1. **`tools/fix_supplier_ids.py`** — after a netlist-rebuild import, component SupplierId is often set to
   the MPN instead of the C-number, which raises a "supplier mismatch" DRC item. This script rewrites it
   from the netlist by designator. It reads *your* netlist JSON, so **if the number in the netlist is wrong,
   it will simply propagate the wrong number more consistently** — which is exactly why verification has to
   happen at BOM time rather than relying on this step.

2. **`tools/compare_netlist.py`** — pin-by-pin diff of source netlist against the exported result, to
   confirm the import did not distort anything.

Neither checks whether a number is *correct*; both only check that it was carried through faithfully.
Correctness of the number itself is guaranteed only by this checklist.
