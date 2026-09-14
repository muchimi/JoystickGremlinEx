# Stream Deck (Elgato plugin bridge)

GremlinEx drives Stream Deck hardware through a **Stream Deck plugin** and a localhost WebSocket bridge. Stream Deck software remains running and owns USB (Wave Link / multi-deck safe).

This path does **not** require Bitfocus Companion or OSC for those keys. The model is **Companion-style (Scope B)**: GEX owns unlimited virtual pages (banks), surface variables, multi-step keys, and live feedback — while existing GEX actions (vJoy, Macro, SimConnect, OSC, State, …) remain the connection layer.

## Setup

1. Install the plugin from `streamdeck_plugin/` (see that folder’s README), or use **Options → Stream Deck → Install Stream Deck plugin…**. CodePath must be `app.html`.
2. In GremlinEx **Options → Stream Deck**, enable **Stream Deck bridge** (default port `9020`).
3. Place **JG Ex Button** (and **JG Ex Dial** if needed) on **one** Elgato profile page covering the whole grid — that page is the hardware viewport.
4. Property Inspector should show **Connected to JG Ex**. Each connected deck gets its own GEX device tab.
5. On the GEX Stream Deck tab: **left = pages**, **center = grid**, **right = actions** for the selected key (Overlay-inspired layout).

## Virtual pages (unlimited)

GEX identifies each mapping as `deviceId : kind : gexPage : slot` (1-based GEX page, slot from grid coordinates).

- Add as many pages as you need in the left page list (not limited by Elgato’s ~10 pages).
- **Map to Stream Deck → Change / Next / Previous / Return to Last** sets the active bank and paints titles/images onto live keys.
- Hardware presses resolve against the **active GEX page** + physical slot.
- Elgato profile pages / folders are optional cosmetics — not the source of truth for GEX banks.

## Surface completeness (designer)

On a selected key:

- Grid **Preview: Released | Pressed** toggle shows that state's icon/title/style on the designer keys.
- **Released / Pressed** (or **State OFF / State ON**) columns — each has icon, up to 3 title lines, and its own Style (font/align/background). Blank pressed/ON title falls back to released/OFF.
- **Appearance** driver — **Press / Release** follows the physical key hold; **GEX State** picks a named state and uses the OFF/ON looks instead.
- **Clear cell** / right-click Delete; **Wipe page** clears the edit page.
- Drag keys onto each other to swap; right-click Copy / Paste.
- Mapped JG Ex keys show a **green ●** badge. Keys that are **not** JG Ex Buttons on the hardware (other Stream Deck plugins) stay visible with a **red ●**. They can still get an icon and background in the designer (for GEX / overlay); mappings stay disabled until a JG Ex Button occupies that slot. Live presses briefly highlight the cell.
- **Stream Deck +** shows a **Dials** row under the key grid.

Right pane stays the normal **InputItemMappingWidget** (no duplicate action UI).

## Surface variables

- Aliased variables sync from GEX States; changing a variable can push back to its alias.
- Variable/state changes re-evaluate appearance and **coalesced-paint** the active page.

## Multi-step keys

Use GEX containers on the right (including **Chain** with **Add Step**) for multi-step behavior on a Stream Deck key. Per-key Steps mode settings remain in the profile model for older mappings but are no longer exposed in the designer toolbar.

## Multi-device

- **One GEX tab per physical Stream Deck**.
- Tabs appear when the plugin reports the deck connected and hide on disconnect; profile mappings are kept.
- Old profiles under a single **Stream Deck** GUID still show a **Stream Deck (legacy)** tab until migrated.

## Map to Stream Deck

1. **Device** — pick a connected Stream Deck.
2. **Function** — **Change Page**, **Next Page**, **Previous Page**, or **Return to Last**.
3. **Page** — for Change Page: 1-based bank number (unlimited).
4. Optional **Auto-return** (Change / Next / Previous) — after a delay, go back to the page that was active before the switch.
5. **Return to Last** — immediately restore the page shown before the current one (history updates on every page change).
6. Optional **Test** switches immediately.

## Designer tips

- Right-click a key → **Link to page** to mirror the same position on another GEX bank (look + mappings). Linked keys show a purple **↗P#** badge; edit the source page instead of copy/paste.
- **Return to Last** (Map to Stream Deck) restores the previously shown bank.

**In scope:** surface editor polish, variables, multi-step, live feedback, integration with existing GEX actions/containers.

**Out of scope (for now):** Companion connection modules (OBS/Twitch/…), Loupedeck/other USB surfaces, Satellite/cloud, full Companion config import, taking USB from Elgato.

Suggest changes to Muchimi as a **PR series** (surface polish → variables → multi-step → feedback), not one mega-PR.

## Related

- Companion / OSC panel setup: [usage.md](usage.md#osc-device-open-sound-control), [mapping.md](mapping.md), [resources.md](resources.md)
- Cursor rule: `.cursor/rules/streamdeck-integration.mdc`
