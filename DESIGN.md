---
name: 微博超话助手 · 黑场追光
description: 本地优先的微博返图文案助手——一间黑场里的调光台，粉色追光照亮本次文案。
colors:
  blackout: "#0c0c11"
  deck: "#12121a"
  deck-2: "#191922"
  deck-3: "#1e1e29"
  well: "#0e0e15"
  beam: "#fff3ee"
  dim: "#a8a1ab"
  dim-2: "#8f8896"
  spot: "#ff4f86"
  spot-2: "#ff7ea6"
  spot-soft: "rgba(255,79,134,.13)"
  amber: "#ffb15e"
  gel: "#6be0d6"
  hair: "rgba(255,243,238,.09)"
  hair-2: "rgba(255,243,238,.17)"
  ink-on-spot: "#2a0713"
  raise: "rgba(255,243,238,.07)"
  track: "rgba(255,243,238,.13)"
  scroll: "rgba(255,243,238,.11)"
  wash-a: "rgba(255,79,134,.10)"
  wash-b: "rgba(107,224,214,.05)"
  lift: "0 14px 40px rgba(0,0,0,.6)"
  blackout-light: "#f2efec"
  deck-light: "#ffffff"
  deck-2-light: "#faf7f5"
  deck-3-light: "#efeae7"
  well-light: "#f4f0ee"
  beam-light: "#1c1719"
  dim-light: "#5c5458"
  dim-2-light: "#756d71"
  spot-2-light: "#d21f5b"
  spot-soft-light: "rgba(210,31,91,.10)"
  amber-light: "#8f5308"
  gel-light: "#0e6f66"
  hair-light: "rgba(28,23,25,.12)"
  hair-2-light: "rgba(28,23,25,.22)"
  raise-light: "rgba(28,23,25,.05)"
  track-light: "rgba(28,23,25,.12)"
  scroll-light: "rgba(28,23,25,.20)"
  wash-a-light: "rgba(255,79,134,.07)"
  wash-b-light: "rgba(14,111,102,.04)"
  lift-light: "0 12px 32px rgba(28,23,25,.18)"
typography:
  display:
    fontFamily: "Bahnschrift, 'DIN Alternate', 'Segoe UI Variable Display', system-ui, 'Microsoft YaHei', sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.02em"
  body:
    fontFamily: "'Segoe UI Variable Display', 'Segoe UI', system-ui, 'Microsoft YaHei', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  label:
    fontFamily: "Cascadia Mono, Consolas, ui-monospace, 'Courier New', monospace"
    fontSize: "10.5px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.11em"
  mono:
    fontFamily: "Cascadia Mono, Consolas, ui-monospace, 'Courier New', monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "0.04em"
  stat:
    fontFamily: "Bahnschrift, 'DIN Alternate', 'Segoe UI Variable Display', system-ui, 'Microsoft YaHei', sans-serif"
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.01em"
  readout:
    fontFamily: "Bahnschrift, 'DIN Alternate', 'Segoe UI Variable Display', system-ui, 'Microsoft YaHei', sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1
  stat-sm:
    fontFamily: "Bahnschrift, 'DIN Alternate', 'Segoe UI Variable Display', system-ui, 'Microsoft YaHei', sans-serif"
    fontSize: "16px"
    fontWeight: 500
    letterSpacing: "0.04em"
  ui:
    fontFamily: "'Segoe UI Variable Display', 'Segoe UI', system-ui, 'Microsoft YaHei', sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.5
  small:
    fontFamily: "'Segoe UI Variable Display', 'Segoe UI', system-ui, 'Microsoft YaHei', sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.7
  micro:
    fontFamily: "Cascadia Mono, Consolas, ui-monospace, 'Courier New', monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0.02em"
rounded:
  line: "2px"
  track: "3px"
  xs: "5px"
  sm: "6px"
  md: "8px"
  lg: "9px"
  xl: "10px"
  pill: "12px"
spacing:
  2xs: "2px"
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "18px"
  2xl: "30px"
components:
  button:
    backgroundColor: "{colors.deck-2}"
    textColor: "{colors.beam}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
    typography: "{typography.body}"
  button-hover:
    backgroundColor: "{colors.deck-2}"
  button-primary:
    backgroundColor: "{colors.spot}"
    textColor: "{colors.ink-on-spot}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  button-primary-hover:
    backgroundColor: "{colors.spot-2}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.beam}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  button-danger:
    backgroundColor: "{colors.deck-2}"
    textColor: "{colors.amber}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  button-tiny:
    backgroundColor: "{colors.deck-2}"
    textColor: "{colors.beam}"
    rounded: "{rounded.sm}"
    padding: "5px 11px"
  card:
    backgroundColor: "{colors.deck}"
    textColor: "{colors.beam}"
    rounded: "{rounded.xl}"
    padding: "18px 18px 16px"
  stat-tile:
    backgroundColor: "{colors.deck-2}"
    textColor: "{colors.beam}"
    rounded: "{rounded.xl}"
    padding: "14px 15px"
  input:
    backgroundColor: "{colors.well}"
    textColor: "{colors.beam}"
    rounded: "{rounded.md}"
    padding: "10px 12px"
    typography: "{typography.body}"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.dim}"
    rounded: "{rounded.md}"
    padding: "9px 10px"
  nav-item-active:
    backgroundColor: "{colors.spot-soft}"
    textColor: "{colors.beam}"
    rounded: "{rounded.md}"
    padding: "9px 10px"
  chip:
    backgroundColor: "rgba(255,243,238,.07)"
    textColor: "{colors.dim}"
    rounded: "{rounded.xs}"
    padding: "2px 9px"
    typography: "{typography.label}"
  chip-ready:
    backgroundColor: "rgba(107,224,214,.14)"
    textColor: "{colors.gel}"
    rounded: "{rounded.xs}"
    padding: "2px 9px"
  chip-pending:
    backgroundColor: "rgba(255,177,94,.15)"
    textColor: "{colors.amber}"
    rounded: "{rounded.xs}"
    padding: "2px 9px"
---

# Design System: 微博超话助手 · 黑场追光

## Overview

**Creative North Star: "黑场 · 追光 (The Blackout Spotlight)"**

This is a lighting console in a dark venue, not a dashboard. The floor is black (`#0c0c11`); the app's one job is to put a pink spotlight on the thing you are working on — the caption being written, the channel that is live, the heading you are reading. Everything else stays dim, in the haze. The model is the lamp; you are the lighting operator; the fader is the gesture that ends in a version.

The world is built from stage materials rather than UI chrome: a blackout stage, a console deck a hair lighter than the floor, a warm-white beam for text, a spotlight cone overhead, gels for status, rocker switches, and vertical Cue lists. Depth is not material elevation — it is emission. Elements do not cast shadows to sit above one another; the lit element emits (a glow, a warm top-edge line, a pink wash) and the unlit element recedes into the floor. The pink accent is a beam, spent sparingly, never a coat of paint.

The interface is deliberately self-explanatory (the product ships to other fan clubs later), so every control keeps a familiar shape even where the styling is theatrical: full-width inputs in recessed wells, plain buttons, a numbered channel nav. The theming rides on top of a legible operating surface, not in place of one.

**Key Characteristics:**
- Black-floor world: every surface is the blackout, the deck, or a hair lifted from it — never light.
- Pink as the single lit subject: `--spot` marks the current channel, the page heading, the live result.
- Status is carried by gels: amber `#ffb15e` for pending/maybe, cyan `#6be0d6` for likely/ready.
- Depth by emission: glows, warm top-edge light lines, and the spotlight cone; no structural drop shadows.
- Two type voices: a DIN-lettered technical display face for headings/readouts, and a mono face for every label, channel number, and meta line.

## Colors

A near-black stage that is almost entirely neutral, lit by exactly one brand beam (pink) plus two channel-status gels.

### Primary
- **Spotlight Pink** (`--spot` #ff4f86): the brand beam and the only "this one is live" color. The active nav channel dot, the bullet beside an `h2`, the lit result border and top line, the fader fill, the primary button, and the text selection all draw from it. **Spotlight Pink Light** (`--spot-2` #ff7ea6) is its lit top edge in gradients; **Spotlight Wash** (`--spot-soft` rgba(255,79,134,.13)) is its 13%-alpha halo for rings, focus glows, and the active-channel background wash.
- **Ink on Spot** (`--ink-on-spot` #2a0713): the near-black maroon printed on top of a lit pink key. Used for primary-button text and selection text so the beam stays readable.

### Secondary
- **Stage Amber** (`--amber` #ffb15e): a channel-status gel for the unsettled — pending events, "maybe" matches, warning/danger text, the fader's numeric readout, and the `code` color. It means "not yet confirmed", never decoration.

### Tertiary
- **Gel Cyan** (`--gel` #6be0d6): the other channel-status gel, meaning "ready / trustworthy" — the "likely" and model-ready tags. Also appears once as a faint body-background radial wash, a distant cold light in the haze.

### Neutral
- **Blackout** (`--blackout` #0c0c11): the page floor. The body background is this color plus two fixed radial washes (a pink pool at top-right, a cyan pool at bottom-left).
- **Deck** (`--deck` #12121a): the console body — the sidebar gradient's dark end and every card surface. **Deck Highlight** (`--deck-2` #191922) is the lit face: card/stat gradients' light end, list-row background, toast, and the default key.
- **Well** (`--well` #0e0e15): the recessed input channel behind every field, select, textarea, and switch track.
- **Beam** (`--beam` #fff3ee): the warm-white body/primary text and the bright end of gradients. Warm, never pure white, so the blackout reads warm-lit rather than clinical.
- **Haze** (`--dim` #a8a1ab) and **Far Haze** (`--dim-2` #8f8896): secondary and tertiary text. Far Haze is the floor for small meta text and is kept ≥4.5:1 against Deck Highlight.
- **Hairline** (`--hair` rgba(255,243,238,.09)) and **Hairline Bright** (`--hair-2` rgba(255,243,238,.17)): the 1px borders and top-edge light lines that separate panels without any solid rule.

### Named Rules
**The Blackout Rule.** The dark rendition's page floor is `--blackout` `#0c0c11` and never leaves it. Every surface is that floor, `--deck`, `--deck-2`, or `--deck-3` — a hair lifted, never a light card.

**The House Lights Rule.** There is exactly one other rendition, and it is not an inversion. `[data-theme="light"]` is the *same console with the house lights up*: the floor becomes warm paper (`#f2efec`), the decks become white, the beam inverts to warm near-black. What never changes is the light: pink is still the brand and still marks the single lit subject, the fader fill and the primary key stay pink, and the two gels only **darken into ink** (`--amber` `#8f5308`, `--gel` `#0e6f66`) so they stay legible on a lit ground. Nothing that is a lamp in the dark becomes a shadow in the light.

**The One Beam Rule.** Pink is a beam, not a coat. On any screen it marks the single lit subject (the current channel, the heading bullet, the live result) plus at most one lit key. Bulk pink fills are limited to a 1px border, a 13%-alpha wash, or one button; the beam's rarity is what makes it read as light.

**The Gels Are Status Rule.** Amber and cyan are channel状态 only. If a color is not saying "pending" or "ready/trustworthy", it must come from the neutral ramp.

## Typography

**Display Font:** Bahnschrift (with DIN Alternate, Segoe UI Variable Display, system CJK fallback)
**Body Font:** Segoe UI Variable Display (with Segoe UI, system-ui, Microsoft YaHei)
**Label/Mono Font:** Cascadia Mono (with Consolas, ui-monospace, Courier New)

**Character:** Two voices. A DIN-lettered technical face (Bahnschrift) for the console's headings, stat values, and readouts — the industrial lettering of stage and lighting equipment. A mono face (Cascadia Mono) for every label, channel number, and meta line, so the operating data reads like console printout. The body sits in the system UI face and stays quiet. CJK renders in the system Chinese face; only Latin digits and tags carry the DIN/mono character.

### Hierarchy
- **Display** (600, 24px / `0.02em`): page headings (`h2`). Left-padded 16px with a lit 8px pink bullet before the text. The same face scales up to 30px for stat values (`.stat .v`) and down to 20px for readout figures (`.readout b`) — one display voice, three sizes.
- **Body** (400, 14px, line-height 1.6): body copy, hints, list descriptions; `hint` copy runs at 12.5px / 1.75 and is capped near `min(78ch,100%)`.
- **Label** (mono, 500, 10.5px, `0.11em`, uppercase): form labels, stat keys, tag text, and nav channel numbers. Always tracked and uppercase.
- **Mono / Meta** (mono, 400, 11–12.5px): list meta rows, fader value readouts, counts, timestamps, `code`. Amber on `code`.

### Named Rules
**The Two Voices Rule.** DIN for anything a heading or a number; mono for anything that names or labels. Body text never takes the display face, and display text (headings, stat values, readouts) never takes the body face.

**The Console Print Rule.** Labels, channel numbers, tags, and meta lines are mono, uppercase, and tracked (10.5–12.5px, `0.04–0.12em`). This is what makes the operating data read as instrument readout rather than prose.

## Layout

A fixed instrument rack on the left, a working stage in the middle.

- **App frame** (`.app`): flex row. The **sidebar** is a fixed 216px sticky column (`height:100vh`) holding the brand mark and an 8-item numbered nav. The **main** column flexes (`flex:1; min-width:0`) and is capped at `max-width:1180px` with `padding:30px 34px 90px` (extra bottom room for the toast).
- **Console** (`.console`, the 写文案 workbench): a 3-column grid `236px minmax(0,1fr) 288px` — left fader/parameter strip, center stage, right Cue column. Collapses to two columns at ≤1180px and to one column at ≤900px.
- **Prep row** (`.prep`): a 2-column grid for secondary tools (template, photo), collapsing to one column at ≤900px.
- **Card grid** (`.cards`): `repeat(auto-fill, minmax(168px,1fr))` with a 12px gap.
- **Rhythm**: the recurring spacing steps are 6 / 8 / 12 / 14 / 16 / 18px — list rows at 8px, card grid at 12px, card bottom margin at 14px, the console gutter at 16px, and card padding at 18px. Cards carry `1px` hairline borders and never a solid rule.
- **Narrow screen** (≤820px): the console turns sideways — the sidebar becomes a horizontal top bar with the brand as the first chip and the nav scrolling horizontally; the nav's status dots are dropped and rows stack.

## Elevation & Depth

This is a flat, emission-lit system: **no structural drop shadows.** Nothing sits "above" anything by casting a shadow; a surface is raised only when it emits light. Depth is conveyed three ways — (1) **glow**, a pink halo around the live thing (the active channel's dot, the `h2` bullet, the focused field's ring); (2) **top-edge light lines**, a 1px warm `--hair-2`→transparent gradient along a card's top edge (`.card::before`) and a solid pink line across a lit result's top edge (`.result::before`); and (3) **the spotlight cone**, a blurred pink radial above the stage (`.stage::before/::after`) that makes the center column feel physically lit from a lamp overhead.

The only genuine lift shadow in the system belongs to the transient toast, which floats above everything and is allowed to detach.

### Shadow Vocabulary
- **Spot halo** (`0 0 0 3px rgba(255,79,134,.13)`): the focus ring on inputs and the halo behind the brand dot; a beam's soft edge.
- **Spot glow** (`0 0 10px 1px rgba(255,79,134,.5)`): the `h2` bullet — the live heading emits.
- **Channel glow** (`0 0 9px 1px rgba(255,79,134,.55)`): the active nav channel's status dot.
- **Toast lift** (`0 14px 40px rgba(0,0,0,.6)`): the one true elevation shadow, on the transient toast only.
- **Fader thumb** (`0 0 0 1px rgba(255,243,238,.25), 0 3px 8px rgba(0,0,0,.6)`): the physical handle on a fader track.
- **Lit key inset** (`inset 0 1px 0 rgba(255,255,255,.35)`): the highlight along the top of a pressed-lit pink button.

### Named Rules
**The Emission Rule.** Depth comes from light, not shadow. To make a thing read as raised or live, give it a glow, a warm top-edge line, or a beam — do not give it a drop shadow.

**The One Shadow Rule.** Only the toast casts a real shadow. If a static panel needs to feel separated, it earns a hairline border, not a shadow.

## Shapes

The form language is soft-edged panel and hard-edged instrument. Panels (cards, stat tiles, readout, result, stage-empty) share a single 10px radius (`--radius`). List rows and empty states drop to 9px; inputs, buttons, and nav rows to 8px; tiny keys and the photo file-selector to 6px; tag chips to 5px; the rocker-switch track is a 12px pill. Borders are always thin (1px) hairlines in `--hair` or `--hair-2`, and dashed hairlines mark an empty or optional slot (the stage-empty frame is a dashed pink border). Circles are reserved for the light dots: the brand mark, the heading bullet, the nav status dot, and the switch knob.

## Components

### Buttons
- **Shape:** panels at 8px radius (`--rounded.md`), padding `10px 16px`, body face 13px/500.
- **Primary ("上光"):** a lit pink key — gradient `--spot-2`→`--spot`, `--spot` border, `--ink-on-spot` bold text, an inset white top highlight. This is the "put the light on it" action and there is normally one per surface.
- **Hover / Focus:** default keys brighten their gradient and ring to `rgba(255,243,238,.3)`; the primary key lightens to `#ff93b6`→`--spot-2`; all keys translate down 1px on `:active`; transitions run ~0.14s.
- **Ghost:** transparent background with a faint `rgba(255,243,238,.05)` hover — used for secondary/clearing actions.
- **Tiny:** 6px radius, `5px 11px`, 12px text — list-row ops and inline utilities.
- **Danger:** `--amber` text on a deck key with a `rgba(255,177,94,.35)` border — a warm warning state, not a red alarm (this world has no red).
- **Disabled:** 45% opacity, `not-allowed` cursor.

### Chips
- **Style:** a small gel — 5px radius, `2px 9px`, mono 10.5px/`0.05em`. Default fill `rgba(255,243,238,.07)` with `--dim` text.
- **State:** status is the gel. Ready/likely → cyan fill + `--gel` text; maybe/pending → amber fill + `--amber` text; accent → `--spot-soft` fill + `--spot-2` text.

### Cards / Containers
- **Corner Style:** 10px (`--radius`).
- **Background:** `--deck`, flat, over the blackout floor.
- **Shadow Strategy:** none — a warm `--hair-2` top-edge light line instead (see Elevation).
- **Border:** 1px `--hair` hairline, all sides.
- **Internal Padding:** `18px 18px 16px`.

### Inputs / Fields
- **Style:** recessed well — `--well` background, 1px `--hair` border, 8px radius, `10px 12px`, body face 13.5px; selects drop the native arrow for a two-gradient chevron in `--dim`; file inputs use a dashed `--hair-2` border with a custom mono file-selector button.
- **Focus:** border turns `--spot`, background deepens to `#101018`, and a 3px `--spot-soft` ring appears — the field catches the beam.
- **Placeholder:** `--dim-2`.

### Navigation
- **Style:** a vertical channel strip. Each row is a 3-track grid (`26px 1fr 8px`): a mono leading-zero counter (`01`–`08`), the label, and a right-aligned status dot. Default text `--dim` at 13.5px on a transparent 8px-radius row.
- **Active:** a left-to-right `--spot-soft`→transparent wash, `--beam` text, a `--hair` border, the counter number in `--spot`, and the status dot lit to `--spot` with a channel glow.
- **Hover:** `rgba(255,243,238,.035)` background, text brightens to `--beam`.
- **Mobile (≤820px):** the strip turns horizontal in the top bar; the status dot is dropped and the counter keeps the number.

### Fader (signature)
- **Track:** a 4px 2px-radius rail filled `--spot` up to the current value (via a `--v` custom property) and `rgba(255,243,238,.13)` after.
- **Thumb:** a physical 15×27px rounded handle — white→`--beam` gradient, 1px black border, the fader-thumb shadow; `grab` cursor.
- **Readout:** the value sits in mono `--amber` beside the rail, right-aligned. The fader is the product's memorable gesture — sliding it re-lights the caption.

### List / Cue
- **Style:** a vertical stack of `--deck-2` rows at 9px radius, a 3-track grid (mono counter, body, ops), `12px 14px`. Hover lifts the row to `#1c1c26` with a `--hair-2` border and lights the counter pink. Rows carry a title (`--beam`, 600), a description (`--dim`, 12.5px), and a mono `--dim-2` meta line.
- **Empty state:** a dashed `--hair` frame, centered mono `--dim-2` copy — "the stage is empty" register.

### Switch
- **Style:** a rocker pill, 40×22px, `--well` track with a `--dim` 16px knob. Checked → `--spot-soft` track with a `--spot` border and a knob that slides 18px and turns `--spot`.

### Stage / Result (signature)
- **Stage:** the center column of the console, `min-height:330px`, isolated, with the spotlight cone (blurred pink radial + overhead halo) rendered behind it. Empty, it shows a dashed-pink frame reading "舞台空着".
- **Result:** the lit caption — a pink-tinted gradient background `rgba(255,79,134,.10)`→`.03`, a `rgba(255,79,134,.28)` border, a solid pink top-edge line, an editable textarea, and a mono "used sources" footnote. This is the beam actually landing.

### Beam progress
- A 3px rail (`rgba(255,243,238,.08)`) that, while generating, sweeps a `--spot` highlight across itself on a 1.05s linear loop — the visible "the lamp is warming up" signal the slow 4GB GPU demands.

## Do's and Don'ts

### Do:
- **Do** keep the floor at `--blackout` `#0c0c11` and build every surface from `--deck` / `--deck-2` / `--well` — black, or a hair lifted (The Blackout Rule).
- **Do** spend pink as a beam: lit subject + at most one lit key per screen, in a 1px border, a 13%-alpha wash, or a single button (The One Beam Rule).
- **Do** carry status with gels — amber `#ffb15e` pending/maybe, cyan `#6be0d6` ready/likely (The Gels Are Status Rule).
- **Do** convey depth by emission — glow, warm top-edge light line, spotlight cone — and reserve a real drop shadow for the toast alone (The Emission Rule).
- **Do** set headings, stat values, and readouts in the DIN display face and every label, channel number, tag, and meta line in tracked uppercase mono (The Two Voices Rule).
- **Do** keep secondary text on `--dim` / `--dim-2`, holding `--dim-2` at ≥4.5:1 against `--deck-2`.

### Don't:
- **Don't** introduce a light surface, a white card, or a light theme; the world never leaves the blackout.
- **Don't** coat a region in pink — no pink section backgrounds or pink-filled lists. Pink fills stay at hairline / 13%-wash / single-key scale.
- **Don't** use drop shadows for structure; a static panel earns a hairline border, not elevation (The One Shadow Rule).
- **Don't** let body or UI prose take the display face; DIN is for headings and numbers only (The Two Voices Rule).
- **Don't** use amber or cyan for anything but channel status — they are gels, not a decorative palette.
- **Don't** add a second competing accent color; the pink beam plus the two status gels are the whole chromatic budget.
- **Don't** reinvent the nav, inputs, or keys as novel shapes — the world is theatrical in color and light, but the operating controls stay familiar so the app is self-explanatory to a new站子.
