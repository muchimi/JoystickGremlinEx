# Stream Deck (Elgato plugin bridge)

GremlinEx can use Elgato Stream Deck hardware through a dedicated **Stream Deck plugin** and a localhost WebSocket bridge. Stream Deck software remains running and owns USB, so other decks can still run Wave Link or other plugins on the same PC.

This path does **not** require Bitfocus Companion or OSC for those keys. Companion + OSC remain available for glass surfaces and users who prefer that stack.

## Setup

1. Install the plugin from `streamdeck_plugin/` (see that folder’s README). CodePath must be `app.html` (classic Stream Deck HTML host).
2. In GremlinEx **Options → OSC/MIDI**, enable **Stream Deck bridge** (default port `9020`).
3. Place **JG Ex Button** (or **JG Ex Dial**) actions on Stream Deck keys. Customize icons/titles in Stream Deck software.
4. Property Inspector status should show **Connected to JG Ex**. Each connected deck gets its own GEX device tab (named from Elgato, e.g. **Stream Deck XL**, **Stream Deck +**) with **Plugin: connected**.
5. Set a stable **Button ID** and **Page** in the Property Inspector (Page defaults to `1`).
6. Map the auto-created inputs on that deck’s GremlinEx tab (containers / Map to VJoy / etc.).

## Page-scoped mappings

GEX identifies each Stream Deck input as `deviceId : kind : page : buttonId` (page is 1-based).

- The same **Button ID** on different Elgato profile pages is intentional and supported — each page is a separate GEX input (e.g. `P1 · …` vs `P2 · …`).
- Set **Page** on each JG Ex Button / Dial to match the Elgato profile page that hosts it. Seeded JG Ex multi-page profiles write this automatically.
- Only the currently visible page’s keys are live (Elgato only sends events for visible actions); profile mappings for other pages are kept.
- Older profiles without a `page` value are treated as **page 1**.

This is separate from **Map to Stream Deck → Change Page** title feedback (`P1` / `P2` via `setTitle`). Real per-page bindings use Elgato profile pages plus the **Page** setting.

## Multi-device

- **One GEX tab per physical Stream Deck** (joystick-like). Inputs for a deck stay under that deck’s stable GUID.
- Tabs appear when the plugin reports the deck connected (`device` / `willAppear`) and hide when it disconnects; profile mappings are kept.
- Old profiles that stored everything under a single **Stream Deck** GUID still show a **Stream Deck (legacy)** tab until those inputs are migrated (happens automatically when that deck reconnects and `device-id` is present).

## Plugin profiles (Change Page)

The plugin ships **one profile per Elgato DeviceType** (pages are pages inside that profile — never one profile per page):

| DeviceType | Profile | Typical hardware |
|---|---|---|
| 2 | `profiles/jgex-xl` | Stream Deck XL |
| 7 | `profiles/jgex-plus` | Stream Deck + |
| 0 | `profiles/jgex` | Classic / MK.2 |
| 1 | `profiles/jgex-mini` | Mini |
| 9 | `profiles/jgex-neo` | Neo |

Stream Deck **+** keys use **JG Ex Button**; encoders use **JG Ex Dial**.

## Two-way control

Use the **Map to Stream Deck** action on any button-like input:

1. **Device** — pick a Stream Deck reported by the connected plugin (Refresh if needed).
2. **Function** — currently **Change Page**.
3. **Page** — page number on that device’s **JG Ex** plugin profile (`1` = first page).
4. Optional **Test** button sends Change Page immediately.

**Important (Elgato SDK):** plugins cannot change pages on arbitrary user profiles (e.g. “Profile 1”). Change Page switches to the bundled JG Ex profile for that device type at the requested page. Close the Stream Deck editor, accept the profile install if prompted, and place your buttons on that profile’s pages.

## Related

- Companion / OSC panel setup: [usage.md](usage.md#osc-device-open-sound-control), [mapping.md](mapping.md), [resources.md](resources.md)
