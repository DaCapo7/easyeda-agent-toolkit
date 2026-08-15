English | [简体中文](./component-sourcing.zh.md)

# Component Sourcing: from requirements to part numbers

This document covers the very front of the chain: **how circuit requirements become a BOM carrying LCSC
C-numbers**. There is no script to run here — this stage is research. What the repository supplies instead
is **prompt templates**: hand a template to any AI with web search available, have it produce candidates
against a uniform evidence standard, and close the stage with a verification checklist.

The templates are AI-agnostic. They do not say "you are model X", they assume no knowledge of your project,
and every blank is marked with an 〈angle-bracket〉 placeholder. Hand them to a different AI and they work
the same way.

---

## Position in the chain

```
requirement specification    ← turn circuit requirements into a searchable parameter table
      │  prompts/component-sourcing-brief.en.md
      ▼
sourcing research            ← AI searches candidates, returns a primary and alternates
      │  prompts/part-number-verification.en.md
      ▼
part numbers fixed / BOM     ← written into the BOM's Supplier Part column only after verification
      │  tools/tel2json_netlist.py
      ▼
netlist rebuild import       ← docs/netlist-import.en.md
      │
      ▼
PCB / clearance remediation / manufacturing files
```

**Why sourcing is treated as a stage of its own.** Every automated step downstream rests on one assumption:
that `Supplier Part` in the BOM is correct. Once that assumption fails, each subsequent step merely
propagates the error more consistently — `tel2json_netlist.py` faithfully writes the wrong number into the
netlist, the import faithfully places the wrong component, and `fix_supplier_ids.py` faithfully makes the
wrong number more uniform. No step anywhere in the chain will tell you the number itself was wrong.

The quality of this stage therefore determines what the automation downstream is worth.

---

## The two templates

### `prompts/component-sourcing-brief.en.md` — sourcing brief

The brief you hand to an AI. You fill in the requirements (electrical parameters, package, temperature
range, cost ceiling, assembly constraints, target assembly service, supply requirements); it returns a
candidate comparison table built to a fixed evidence standard.

The hard constraints written into the template:

- Every candidate must carry a **verifiable supplier part number plus a manufacturer part number (MPN)**.
  Both are required, never one.
- Every parameter claim must be **traceable to the manufacturer's datasheet**, with the source and the
  location within it stated.
- Stock and price must carry a **timestamp and a channel**.
- **Producing part numbers from memory is barred**; anything not actually retrieved goes into a separate
  "unverified" section.
- **If the specification cannot be met, say so** — which requirement fails, by how much, and which single
  constraint could be relaxed to resolve it. Lowering the bar quietly to produce an answer is not allowed.
- The output must include an "open questions" section and an "unverified items" section. The latter may be
  empty but must not be omitted.

The comparison table must be filled line by line, including **library membership (basic / extended) and its
setup-fee implication** — in JLCPCB's assembly service, basic-library parts generally carry no feeder setup
fee while extended-library parts incur a one-off fee per part number. When several candidates meet the same
specification, that item often affects small-batch total cost more than unit price does.

### `prompts/part-number-verification.en.md` — verification checklist

The gate before anything is written into the BOM. Its core is one mandatory rule:

> A C-number counts only after it has been **actually retrieved** from the component library. Retrieved
> means: the search returned a part for that number, stock is above zero, and package and key parameters
> match item by item. Producing numbers from memory, impression, or because they "look right" is barred.

This is stated as a rule because component part numbers are a category where language models fail
particularly quietly: the format is regular and the length is fixed, which makes it easy to emit a number
that is **perfectly well-formed but does not exist**, or that exists and denotes something entirely
different. Neither failure shows any symptom before import.

The checklist ticks through six groups: existence, stock, package, parameters, commercial and process, and
consistency. It closes by requiring a "failed" section and an "unverified" section.

Chinese versions: `component-sourcing-brief.zh.md`, `part-number-verification.zh.md`. Content is equivalent.

---

## The two verification channels

### Channel A: web library search

Search by part number or MPN in the LCSC / JLCPCB parts library web interface. No setup required and
available to anyone.

### Channel B: query the library through the bridge, inside EasyEDA

If the bridge and the run-api-gateway extension are already installed per the README, you can query the
component library the EasyEDA client is connected to. The advantage: **you are searching the same library
the import will use**, so there is no "present on the website, absent in the client library" discrepancy.

`examples/30_library_search.js` is that channel:

```bash
# edit KEY (search term) or LCSC_IDS (numbers to verify) in the script, then
python tools/eda_bridge.py run examples/30_library_search.js
```

The two API calls it uses, with signatures taken from the `LIB_Device` reference in the official
easyeda-api-skill:

```js
eda.lib_Device.search(key, libraryUuid?, classification?, symbolType?, itemsOfPage?, page?)
eda.lib_Device.getByLcscIds(lcscIds, libraryUuid?, allowMultiMatch?)
```

Search results expose manufacturer, MPN, supplier part number, package, stock, price, and library
membership (`"standard"` = basic library, `"extend"` = extended library).

**There is a trap in where the fields live.** In the official reference the commercial fields (stock, price,
library category, supplier number, manufacturer) are marked obsolete at the top level and documented as
moved into `otherProperty`; the top-level fields may still be present, or may be empty. For that reason
`30_library_search.js` prints both the **raw key names** found in `otherProperty` and a normalised view —
check what your version actually returns before writing a parser, rather than copying field names from
elsewhere. This follows the same principle as everywhere else in this repository: when in doubt, probe
first rather than trusting the documentation.

---

## Handoff: how sourcing output feeds the rest of the chain

Once the research is accepted, the primary choice's fields go into the BOM per the table below.
`tools/tel2json_netlist.py` reads exactly these column names (several aliases are accepted; the table gives
the recommended spelling):

| BOM column | Value | Downstream use |
|---|---|---|
| `Designator` | Reference designator; comma lists `R1,R2` and ranges `R01-R08` supported | Aligned against designators in the `.tel` |
| `Footprint` | Package name | Feeds second-level matching (footprint + value) |
| `Value` | Electrical value | Feeds second-level matching |
| `Manufacturer Part` | Manufacturer part number (MPN) | Written to `device_name` in the netlist; the way to find a replacement when a number is discontinued |
| `Supplier Part` | LCSC C-number | **The only field that participates in library matching** |

`tel2json_netlist.py` matches designators to part numbers through three fallback levels: exact designator →
footprint + value → unique footprint. Anything that fails all three is **reported as a warning rather than
guessed** — when you see a warning, go back and supply `--override`. Do not let it proceed with an empty
part number.

### Relationship to `fix_supplier_ids.py`

After import, component SupplierId is often set to the MPN rather than the C-number, raising a "supplier
mismatch" DRC item. `tools/fix_supplier_ids.py` rewrites the numbers in bulk from the netlist, by
designator.

**Be clear about what it does and does not do:**

- It **does** guarantee that SupplierId in EasyEDA matches the number written in your netlist.
- It does **not** judge whether that number is correct. If the netlist number is wrong, it will only make
  the wrong number more uniform.

Likewise, `tools/compare_netlist.py` verifies import fidelity — whether the number was carried through
faithfully — not whether the number is right.

Correctness of the number itself is guaranteed only by the verification checklist in the sourcing stage.
That is why sourcing belongs in this repository.
