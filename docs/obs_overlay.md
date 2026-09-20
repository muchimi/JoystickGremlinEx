# Overlay

The Overlay tab draws live physical, vJoy, and GEX state inputs on either a chromakey (or image) window for OBS, or a transparent on-screen HUD. It replaces a Touch OSC + OSC round-trip when you only need a joystick overlay.

## Enable it on a profile

Open the **Overlay** tab (next to Settings and Plugins). Each GEX profile has its own overlay; switching profiles loads that profile’s layout. The tab title shows the active profile name.

Layouts are stored next to the profile XML: `<profile>.json` (key `obs_overlay`) and `<profile>.overlay.json`. Saving the GEX profile (including Save As into another folder) writes the overlay into that same directory under the same name. **Export overlay...** copies the current layout to a JSON file you choose. **Import overlay...** replaces this profile’s overlay with a JSON file.

A user plugin is **not** required. [`user_plugins/obs_overlay.py`](../user_plugins/obs_overlay.py) only adds a Plugins-tab button that jumps to Overlay.

## Pages

The Overlay tab can hold several independent **pages** (sub-tabs under the toolbar). Each page has its own widgets, background, Interactive flag, and live window.

- **Add** with the **+** button. **Rename** by double-clicking a tab (or Canvas → **Name**). Right-click a tab to **Duplicate** or **Delete** (at least one page remains).
- **Show overlay** and **Interactive** on the toolbar apply only to the **selected** page. Other pages keep their own windows and Interactive setting. **Hide overlay** closes that page’s window.
- **Visible** (Canvas, when nothing is selected) closes this page’s live window when unchecked. Per-page **Toggle overlay** and **Show at profile start** can still open other pages.
- Designer edits one page at a time (the active tab). Widgets do not drag between tabs; Duplicate page copies the layout.
- Older layouts load as a single tab named **Overlay**.

## Background modes

### Chroma / image (OBS)

1. Set **Background** to **chroma** or **image**.
2. Click **Show overlay**. That opens the selected page’s window, titled `GEX Overlay — {page name}` (for example `GEX Overlay — HUD`). Switch tabs and click Show overlay again to open another page.
3. In OBS, add a **Window Capture** source for that title.
4. For chroma, add a **Chroma Key** filter. The default key color is `#00FF00`. Set the color’s **alpha to 0** if you want the overlay itself to be transparent so the desktop shows through. That live window is frameless (use the drag bar to move it). The designer canvas shows a checkerboard. OBS window capture still needs an opaque chroma color.
5. Hide the overlay drag bar (right-click the overlay, or uncheck **Overlay drag bar**) before going live.

A background **image** can be used instead of chroma if you want a static HUD plate.

Chroma/image windows remember their **screen position**. **Reset position** (Canvas) clears the saved coordinates and recenters the window. The same reset runs automatically if the saved monitor is gone. On-screen pages cover a chosen monitor instead; Reset position falls back to the primary display.

### On-screen HUD

1. Set **Background** to **on-screen**.
2. Pick the **Monitor**. The canvas width and height update to that monitor’s resolution.
3. Click **Show overlay** (or enable **Show at profile start**). The overlay covers that monitor and stays on top. With **Interactive** off it is click-through so games keep mouse and keyboard focus. With **Interactive** on it captures touch on that screen.

Use **Hide overlay** on the Overlay tab to close the selected page’s on-screen HUD.

## Interactive (touch → vJoy / states)

Check **Interactive** on the Overlay toolbar (or Canvas when nothing is selected). It applies to the selected page only. Touch or click a widget on that page’s live overlay window — not the designer canvas, and not an OBS preview. Physical device bindings stay display-only.

- **vJoy button:** held while pressed, released on lift.
- **State button:** tap inverts the state.
- **Mode button:** tap switches to that mode; tap again leaves it (previous / Default).
- **4-way switch:** press a direction; lift returns to center (and the Center button if bound).
- **2-way toggle:** tap a side; it stays until you tap the other side.
- **3-way switch:** press an end; lift returns to center.
- **Sticks / radar / circular / hat:** drag; lift returns to center.
- **Bar / fader / radio / radial / encoder:** drag; lift keeps the value.
- Multi-touch is supported (one finger per widget). Empty space is click-through so the desktop or game keeps the mouse.

vJoy writes go straight to that device; the profile does not have to be running. Hide overlay to release any held vJoy buttons.

## Profile start

Check **Show at profile start** on a page (Canvas). Activating the profile opens that page automatically if **Visible** is also on, and hides live windows when the profile stops.

**Toggle overlay** (Canvas) is per page: assign a physical, vJoy, GEX state, **mode**, or **keyboard/mouse** the same way widget bindings do. Keyboard/mouse uses the Map to Keyboard/Mouse Ex layout: the current combination is shown in the inspector; **Select...** opens the virtual keyboard popup, and **Listen** / **Listen (multi)** capture keys or mouse buttons. A physical, vJoy, or keyboard/mouse **press** shows or hides **that page’s** window. A **state** or **mode** assignment follows the value instead: the window is shown while the state is pressed / that mode is active, and hidden when it is not. This works whether or not Show at profile start is on.

## Designer

- **Palette:** click to add a widget at the center of the current canvas view. If a widget is already selected, the click changes it to this type and keeps compatible settings (geometry, colors, fonts, and bindings when they still apply).
- **Templates:** dual-stick HUD, Xbox-style gamepad, throttle pair. Saved templates live globally under the GEX data folder (`overlay_templates/`), not in the profile. Use **+** next to **Saved templates** to store the current widgets. An empty canvas is the default for a new profile. Built-in templates are click-to-apply only. Right-click a **saved** template to overwrite it with the current widgets and properties, or to delete it.
- Drag, resize, snap-to-grid, Shift+click multi-select. Hold **Shift** while resizing to keep the aspect ratio (widgets and groups). Right-click selected widgets to duplicate, delete, bring forward, send backward, group, or ungroup. A grouped (or multi-selected) set resizes together from the dashed bounding-box handles. Delete, Ctrl+D, Ctrl+G / Ctrl+Shift+G, Ctrl+Z, and arrow-key nudge still work. Widgets that sit outside a smaller canvas (after a resize or leaving on-screen mode) stay visible in the dark overflow area and can be dragged back; the live overlay still only shows what is on the canvas. The **Hints** banner at the top of the canvas lists the mouse and key actions that apply to the current selection (or the canvas when nothing is selected). Uncheck **Hints** on the toolbar, or close the banner, to hide it.
- Inspector **Geometry** includes **Scale font with size**. **Visibility** (right pane) has the master **Visible** checkbox plus live conditions: mode, GEX state, physical button, vJoy button, or **keyboard/mouse**. Match **All (AND)** or **Any (OR)** — for example “if state Gear is on **and** mode Combat is current then display”, or “if button 4 is pressed **or** state Gear is on then display”. Keyboard/mouse rows use the same combination picker as Map to Keyboard/Mouse Ex (**Select...** opens the popup). Incomplete rows are ignored. The live overlay hides the widget; the designer keeps a faded copy so you can still edit it. Appearance puts **Opacity** (percent slider) above fill color, then widget-specific fill/dot controls. **Grid**, **Crosshairs**, **Axis** (N/S/E/W labels, distance, font), and **Border** (color, width, corner radius) are separate groups. Grids reach the widget border; **Fade at border** tapers them toward the edge.
- **Shape** replaces Panel: rectangle, circle, triangle, diamond, line, freeform, or a **custom** shape you saved. Freeform points are added by double-clicking the outline; drag a point, then drag its yellow handles to Bézier-curve that corner. Hold **Ctrl** while dragging a handle to snap it to 15° steps. Dragging a handle (or point) past the widget edge grows the bounding box so the curve stays inside. Uncheck **Closed** for an open path. Right-click a shape to **Turn into button** (same outline, bind and press like a button) or **Save as custom shape** (adds it to the Shape list for this machine, stored as `overlay_custom_shapes.json` in the GEX data folder).
- **Image** is a separate palette widget. Browse to a PNG, WebP, GIF, JPEG, or BMP. Formats with an alpha channel keep their transparency; Fill is only a backdrop behind those pixels. **Keep aspect ratio** (on by default) fits the picture in the widget instead of stretching it. Right-click an image to **Turn into button** (no label, the picture is the released/off background) or **Turn into paddle** (the picture rotates around its center).
- **Application** shows a live picture of a running window. Pick it from the inspector list (Refresh windows if it was started later). The choice is stored by window title and process name so it can reconnect after a restart. This widget has no joystick binding.
- **Stream Deck** mirrors a connected Elgato deck: pick the device (or First connected), optionally follow the hardware GEX page, and the overlay draws that deck’s keys with the same art as the Stream Deck designer. Stream Deck + also shows the LCD row and dials. **Fit to device** sizes the widget to that layout. This widget has no joystick binding.
- Inspector: size, **Rotation** (−180° to 180°, clockwise), visibility conditions, colors, fonts, line/dot sizes, labels (including fill and border), invert, deadzone, and binding. Drag the round handle above a selected widget to rotate it; hold Shift to snap to 15°. Selecting a **group** (or multiple widgets) shows only shared properties; edits apply to every selected widget. With **Scale font with size** on, Font size shows the size currently drawn and updates while you resize the widget.
- **Guides** (Canvas): add vertical and/or horizontal lines, set a color, drag them on the canvas, or type a percent of width/height. Moving or resizing a widget snaps its left/right/center (or top/bottom/center) to nearby guides.
- **Color palettes** sit at the top of Appearance as two rows: built-in defaults (click to apply) and user palettes. They are per widget type and stored globally (`overlay_color_palettes.json` in the GEX data folder), not in the profile. **+** saves the current colors as a user square. Right-click a user square to overwrite it or delete it. Default palettes cannot be changed. Transparent fills show as a square with a cross. Built-in squares: default, Touch OSC (red), transparent green.

Widget mapping (Touch OSC-style names in the palette):

| Palette | What it is |
|---|---|
| Button | Momentary / state / mode / keyboard button |
| Hat | POV hat (4- or 8-way) |
| 4-way switch | Hat that reports as five buttons: N, E, S, W, and optional center |
| 2-way toggle | Two-position switch; each end is a button |
| 3-way switch | Three-position switch with a spring-loaded center |
| Bar | 1D pad with a moving dot (horizontal or vertical), same language as the X/Y square; N/S labels when vertical, E/W when horizontal |
| Radio | Stepped cells along one axis |
| Fader | Ladder track, fill below the thumb, and a sliding thumb |
| Radial | 270° arc with ticks |
| Encoder | Full donut with ticks and one moving highlighted wedge |
| Temporal graph | One or more physical / vJoy axes over time (Input Viewer–style). Add or remove datasets, set period, min/max, and unit |
| Bar graph | One or more physical / vJoy axes as moving bars. Horizontal or vertical. Auto range is −100…+100 if any axis is centered, otherwise 0…100. Per-axis color and range |
| Counter | One or more live stats in the same widget, each with its own color: time, in-game FPS, CPU, GPU, memory, temperatures, or a keybind tally |
| Stopwatch | Digital mm:ss / hh:mm:ss or analog watch. Bind start/stop and optional reset. Analog hour/minute/second needles have color, width, and arrow |
| Keyboard / Mouse | Live key and mouse-button overlay. Presets (WASD + mouse, full keyboard, mouse only) or pick keys on the virtual keyboard. Separate mouse silhouette / button-map graphics |
| X/Y | 2D square pad; optional lines through the dot, circle/square dot, shadow |
| Radar | Concentric rings, a beam from the center, and a circle through the current position; optional 15/30/45° angle lines |
| Circular | Round 2D pad; optional angle lines |
| Mouse | Live mouse: **VJoy** draws an arrow from rest (length = displacement, **Max displacement** sets full scale); **Standard** shows a top-down mouse that recenters after idle |
| Shape | Rectangle, circle, triangle, diamond, line, freeform Bézier path, or a saved custom shape |
| Image | Custom picture; PNG/WebP/GIF keep transparency. Paste a Windows Snipping Tool screenshot with Ctrl+V, right-click **Paste image**, or inspector **Paste**. Right-click **Turn into button** / **Turn into paddle** |
| Application | Live capture of a running local window. Inspector lists visible applications |
| Stream Deck | Live preview of a connected Elgato Stream Deck |

## Bindings

Each widget (except labels, shapes, images, Application widgets, Stream Deck widgets, **Mouse** widgets, **Temporal graph** widgets, **Bar graph** widgets, **Counter** widgets, and **Keyboard / Mouse** widgets) can bind to:

- a **physical** device axis, button, or hat (use **Listen...** or pick from the lists)
- a **vJoy** axis, button, or hat
- a named GEX **state**
- a GEX **mode** (buttons and Stopwatch): the button uses Pressed fill while that mode is current (unless **Appearance from** is set to a GEX state); a Stopwatch runs while that mode is current
- a **keyboard/mouse** combination (buttons, Toggle overlay, Stopwatch, and Counter increment/decrement/reset): **Select...** opens the Keyboard & Mouse Input Mapper; the inspector shows the current key combination

Button widgets also have **Appearance from**: **Pressed / released** (default) uses the binding above for Released/Pressed fill and border, or **GEX state** to drive State OFF / State ON colors from a state you pick (independent of the binding used for touch/output).

A **4-way switch** binds five buttons (North, East, South, West, Center). Use this when a hat is exposed as discrete buttons instead of a POV hat. Center is optional. A **2-way toggle** binds Position 1 and Position 2. A **3-way switch** binds Up, Center, and Down; if the hardware has no center button, leave Center empty and the widget sits in the middle when neither end is pressed.

A **Label** can check **Show current mode** to display the active profile mode name. The text updates live when you change edit mode, or when the runtime mode changes while the profile is running. The Text field then shows the live mode name and is not edited by hand.

2D sticks and the radar widget have **two independent bindings** (Axis X and Axis Y). Each axis has its own device and axis picker (or Listen). You can mix devices — for example physical X on a stick and vJoy Y on another device.

A **Temporal graph** has a **Datasets** list instead of a single binding. Each dataset is a physical or vJoy axis (Listen or pick). **Period** is how many seconds of history are shown. **Min** / **Max** set the vertical scale; **Unit** is drawn next to those labels. The live overlay samples at the same 60 Hz poll as other widgets.

A **Bar graph** uses the same Datasets list. **Orientation** is vertical (bars grow up) or horizontal (bars grow right). Each dataset has a **Range**: Auto, Centered (−100 to +100), or 0 to 100%. Auto treats sliders/throttles as 0–100 and stick axes as centered. If any selected axis is centered, the scale includes negatives; if every axis is 0–100, there is no negative region. Uncheck **Auto range** to type Min / Max. Bar color is per dataset.

A **Counter** has no joystick binding on the widget itself. **Datasets** list the values to show (time, in-game FPS, CPU usage/clock/temperature, GPU usage/temperature, memory, or a **Manual counter**). Each row has its own color and optional caption. **Orientation** stacks rows or places them side by side. FPS is the foreground game’s frame rate when **MSI Afterburner / RTSS** is running; otherwise it shows n/a. CPU/GPU temperature and GPU usage come from Libre Hardware Monitor, NVIDIA NVML, or Windows GPU Engine counters when those are available.

A **Manual counter** (for deaths, kills, and similar tallies) lives in Datasets. Bind **Increment** and optional **Decrement** / **Reset** the same way as other overlay buttons (keyboard/mouse, physical, vJoy, state, or mode). A press adds or subtracts **Step**; the value does not go below zero.

A **Stopwatch** binds **Start / stop** like a button (physical, vJoy, state, mode, or keyboard/mouse). A press toggles run/pause; a GEX state or mode keeps the clock running while that input is on. **Reset** is an optional second binding. **Display** is a digital counter or analog watch. Analog hour, minute, and second needles each have color, width, and an optional arrow at the tip.

A **Keyboard / Mouse** widget has no joystick binding. Pick a **Preset** (WASD + mouse, WASD + extra mouse, full keyboard, full keyboard + mouse, mouse only, or all picker keys) or **Select keys…** to choose keys on the same virtual keyboard as Map to Keyboard/Mouse Ex. **Select all** / **Deselect all** apply to that picker. Off/On fill, border, and font follow the other overlay widgets. **Mouse graphic** is a top-down silhouette or a labeled button map (M1–M5, wheel up/down, tilt, double-click). Only selected keys and mouse buttons light when pressed.

## Notes

- For OBS, capture **GEX Overlay — {page name}**, not the Overlay tab. Each page is a separate window.
- Layouts are per profile. Saving the GEX profile writes `<profile>.overlay.json` (and the overlay key in `<profile>.json`) next to that profile XML. **Export overlay...** copies the layout to another file. **Import overlay...** loads a JSON file into the current profile.
- Axis labels (N/S/E/W) have their own font, size, weight, color, and **Distance from center** slider in the inspector (100 = near the border with even padding; 0 = stacked at the center). 2D sticks and hats use all four; bars show North/South when vertical and East/West when horizontal.
- **Deadzone display** is overlay-only. Axis values inside that range around center are drawn as zero; it does not change GEX mappings.
- Photoreal HOTAS meshes, DJ decks, and an OBS Browser Source path are not in this version.
