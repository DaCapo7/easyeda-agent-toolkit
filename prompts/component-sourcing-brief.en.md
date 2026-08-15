# Component Sourcing Brief (template)

How to use: copy this whole template to any AI with web search available, fill in the
〈angle-bracket〉 placeholders, and delete optional rows you cannot fill.
The template targets no particular AI product and assumes the executor knows nothing about your project.

---

## Role

You are a component sourcing researcher. Your task is to find purchasable part numbers that satisfy the
requirements below, and to back every recommendation with verifiable evidence.

You know nothing about this project and do not need to. Do not invent constraints that the requirements
do not state. Where a gap affects your conclusion, list it under "Open questions" at the end rather than
filling it with a guess.

---

## Requirements

### Function

〈One sentence on what this part does in the circuit, e.g. "LDO regulator supplying the 3.3 V digital rail"〉

### Electrical

| Item | Requirement |
|---|---|
| Key parameter 1 | 〈name and range, e.g. output voltage 3.3 V ±2%〉 |
| Key parameter 2 | 〈e.g. continuous output current ≥ 500 mA〉 |
| Key parameter 3 | 〈e.g. input voltage 4.5–12 V〉 |
| Other electrical constraints | 〈e.g. quiescent current < 50 µA; PSRR ≥ 60 dB @ 1 kHz〉 |

### Package and mechanical

- Package: 〈e.g. SOT-23-5 or SOT-89, first preferred; or "any, height ≤ 1.2 mm"〉
- Minimum pin pitch: 〈e.g. ≥ 0.5 mm, limited by fab capability〉
- Maximum board area: 〈e.g. 3 mm × 3 mm〉

### Environment and grade

- Operating temperature: 〈e.g. −20 to +85 °C〉
- Qualification: 〈e.g. AEC-Q100; or "none required"〉

### Cost

- Unit price ceiling: 〈e.g. ≤ 0.20 USD @ 100 pcs〉
- Target volume: 〈e.g. 50 pcs first build, 2000 pcs/year in production〉

### Assembly constraints

- Target assembly service: 〈e.g. JLCPCB SMT prototype assembly〉
- Process: 〈e.g. SMD only, no through-hole; or "limited hand-soldered through-hole acceptable"〉
- Library preference: 〈e.g. prefer JLCPCB **basic** library; extended-library parts must state whether the
  setup fee is acceptable〉

> **Why library membership matters.** In JLCPCB's assembly service, basic-library (`standard`) parts
> generally carry no extra feeder setup fee, while extended-library (`extend`) parts incur a one-off setup
> fee per part number. When several candidates meet the same specification, library membership often affects
> small-batch total cost more than unit price does. The comparison table must therefore include it.

### Supply

- Purchasing channel: 〈e.g. LCSC / JLCPCB parts service〉
- Minimum stock: 〈e.g. in-stock quantity ≥ 3× target volume〉
- Lifecycle: 〈e.g. NRND or EOL parts not acceptable〉

### Other

〈e.g. must share a package with an existing part; or a second source in the same package is required〉

---

## Search and evidence requirements

This section is a hard constraint. Research that does not meet it is void.

1. **Every candidate must carry a verifiable supplier part number** (for example an LCSC C-number) **and a
   manufacturer part number (MPN)**. Both are required — the supplier number drives ordering and library
   matching, the MPN lets anyone re-check parameters and lifecycle on the manufacturer's side.
2. **Every parameter claim must be traceable to a datasheet.** Give the manufacturer's datasheet source
   (page URL or document number plus revision/date) and say where in it the parameter appears (section or
   table). Do not rely on a third-party parametric listing as the sole source.
3. **Stock and price must be timestamped** — both change constantly. State which channel the figure is from.
4. **Never produce a supplier part number from memory.** Numbers must come from an actual search performed
   in this task. Any number you did not actually retrieve must be labelled "unverified" and listed
   separately; it must not appear among the main results. Final confirmation follows
   `part-number-verification.en.md`.
5. **If nothing meets the specification, say so.** State exactly which requirement fails and by how much,
   and suggest which single constraint could be relaxed to resolve it. Do not quietly lower the bar to
   produce an answer.
6. **Separate what you found from what you inferred.** Mark inferences explicitly and state what they rest on.

---

## Required output

### 1. Conclusion

Two or three sentences: which part you recommend and why. If the specification cannot be fully met, say so
in the first sentence.

### 2. Comparison table

At least one primary choice and two alternates. Compare line by line, not just final verdicts:

| Item | Primary | Alternate A | Alternate B |
|---|---|---|---|
| Manufacturer part number (MPN) | | | |
| Manufacturer | | | |
| Supplier part number | | | |
| Package | | | |
| 〈Key parameter 1〉 | | | |
| 〈Key parameter 2〉 | | | |
| 〈Key parameter 3〉 | | | |
| Operating temperature | | | |
| Library (basic / extended) | | | |
| Setup fee impact | | | |
| Unit price (state volume and date) | | | |
| Stock (state channel and date) | | | |
| Lifecycle status | | | |
| Datasheet source | | | |

Fill every cell. Where something genuinely cannot be found, write "not found" — do not leave blanks and do
not write "approximately" or "around".

### 3. Rationale

Explain the primary choice against the alternates in terms of specific parameters or cost. Avoid
contentless phrasing such as "better performance". If the primary choice trades away something, name what.

### 4. Risks and notes

- Single-source risk, lifecycle risk, stock volatility.
- Parameter margin: how much headroom each key parameter has against the specification. Call out anything
  running close to the limit.
- Assembly risk: whether the package needs stencil or reflow-profile attention, or is prone to tombstoning
  or open joints.
- Substitutability: if the primary goes out of stock, can an alternate drop in? Pin-compatible? Equivalent
  parameters? Does the board have to change?

### 5. Open questions

List anything the requirements left unclear that affects the conclusion. For each, give the branch —
"read as X, the answer is A; read as Y, the answer is B" — so it can be resolved in one round.

### 6. Unverified items

Any number or parameter mentioned from impression rather than actual retrieval goes here.
This section may be empty, but it must not be omitted.

---

## Handoff

Once the research is accepted, the primary choice feeds the BOM used by the netlist stage:

| BOM column | Value |
|---|---|
| `Designator` | reference designator |
| `Footprint` | package name |
| `Value` | electrical value (resistance, capacitance, voltage, ...) |
| `Manufacturer Part` | manufacturer part number (MPN) |
| `Supplier Part` | supplier part number (LCSC C-number) |

`Supplier Part` is the critical field in the whole chain — the import looks up library parts by it, and a
wrong value places the wrong component with no way to correct it afterwards. Run the
`part-number-verification.en.md` checklist before writing anything into the BOM.
