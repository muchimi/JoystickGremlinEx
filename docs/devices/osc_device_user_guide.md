# OSC Device User Guide

Use the **OSC** device tab to map controls from a touch panel, another app, or a script. GremlinEx (GEX) receives Open Sound Control messages over UDP. A message has an address such as `/gex/test/button` and can carry arguments such as a button state or a fader position. [OSC 1.0 specification](https://opensoundcontrol.stanford.edu/spec-1_0.html)

## Connect the sender to GEX

1. Open **Options → Modules** and enable **OSC**. Restart GEX if you changed the setting.
2. Open **Options → OSC/MIDI** and check **Enable OSC**. Note the **GremlinEx IP** and **Input port**. The default UDP input port is `8000`.
3. Set your panel or app’s OSC destination to that IP and input port. For a panel on another device, use **Select** next to **GremlinEx IP** to choose the GEX computer’s LAN address. A sender on the same PC can send to the displayed address too. Use `127.0.0.1` if GEX is listening on loopback.
4. If Windows Firewall blocks a sender on your LAN, allow inbound UDP to the selected input port on the private network.

**Output IP** and **Output port** are defaults for messages sent from GEX. The default output port is `8001`. Use the receiving app’s listen port when sending feedback.

## Add an OSC input

1. Open your profile, select the edit mode, and open the **OSC** tab.
2. Click **Add**. In **OSC Input Mapper**, enter the address in **Cmd**, including the leading slash. To learn an address and its arguments, click **Listen for input**, then operate the panel control once. The listener shows the IP and port it is using.
3. Select **Message only** so messages with the same address can carry different values. Select the **Action mode** for the control. For a captured message with several arguments, choose the one to use under **Source**. For example, you can add two axis inputs for an XY pad with the same address and select a different argument on each row.
4. Click **OK**. Select the input row, add a **Basic** container and an action, then save and activate the profile to test it.

| Sender | Input setup | Result |
| --- | --- | --- |
| Momentary button or switch that sends `1` and `0` | Select **Button** and leave **Trigger on message** off. | A nonzero value presses the button. Zero releases it. |
| Command with no arguments | Select **Button** and enable **Trigger on message**. Set the release delay. | GEX presses the button when the message arrives and releases it after the delay. **Autorelease on no arg messages** in **Options → OSC/MIDI** also enables this behavior for argument-free button messages. |
| Fader or slider that sends a value from `0.0` to `1.0` | Select **Axis** and choose the numeric argument under **Source** if the message has more than one. | GEX maps `0.0` to `−1.0`, `0.5` to center, and `1.0` to `+1.0`. Attach **Virtual Remap** to drive an output axis. |
| Numeric update you want to handle as a press | Select **Change**. | GEX emits a press for each matching numeric message, including zero. Use a press-triggered action. |

## Bitfocus Companion example

For Stream Deck setup and the full button walkthrough, see the [Bitfocus Companion Setup Guide](bitfocus_companion_setup_guide.md).

In this setup, Companion and GEX run on the same Windows PC. Companion sends button events to GEX, and GEX uses the profile’s keyboard ex bindings to control Star Citizen.

| Connection | Settings from this setup |
| --- | --- |
| Companion **Generic → OSC** connection, named `osc` | **UDP**, target `192.168.1.95:8000`, feedback listener enabled on UDP `8001`. |
| GEX **Options → OSC/MIDI** | **GremlinEx IP** `192.168.1.95`, **Input port** `8000`. |
| Companion web admin | `http://127.0.0.1:8010` on this PC. Open it to edit the connection and buttons. |

Use your GEX computer’s selected listener address in Companion’s target settings. `192.168.1.95` is the address used in this example. [Bitfocus Generic OSC documentation](https://bitfocus.io/connections/generic-osc)

### Toggle the landing gear

1. In Companion, edit the gear button. Under **Press actions**, add the `osc` connection’s **Send float** action with path `/gear_toggle` and value `1.0`. Under **Release actions**, use **Send float** with the same path and value `0.0`.
2. In GEX, open the SC Ex profile’s **Default** mode and select `/gear_toggle` in the **OSC** tab. To recreate the input in another profile, use **Message only**, **Button**, and the first argument. Leave **Trigger on message** off because Companion sends the release.
3. Add **Map to Keyboard/Mouse Ex** in a **Basic** container. Select **N**, choose **Pulse**, set the duration to **125 ms**, and configure the action to execute on press only. The saved SC Ex mapping also plays a sound on press to acknowledge the command. [Map to Keyboard/Mouse Ex User Guide](../actions/keyboard_ex_user_guide.md)
4. Verify that `N` is bound to the landing gear in Star Citizen, activate the profile, and press the Companion button in the game. GEX sends one key pulse even if you hold the Companion button. Releasing the Companion button resets the OSC input for the next press.

### More SC Ex button mappings

These Companion buttons also send a float `1.0` on press and `0.0` on release. In GEX they use **Message only**, **Button**, and **Map to Keyboard/Mouse Ex**. Use the keys assigned in your Star Citizen controls if they differ from the saved profile.

| Star Citizen control | OSC path | SC Ex keyboard output | **Trigger on message** |
| --- | --- | --- | --- |
| Toggle ship lights | `/lights_toggle` | **L**, Hold | Off |
| Toggle VTOL | `/vtol_toggle` | **K**, Hold | On, with a 250 ms autorelease delay |
| Flight ready | `/flight_ready` | **Right Alt + R**, Hold | Off |

These mappings send keyboard input. For commands advertised by the game’s local server or for feedback driven by actual ship state, see the [Star Citizen Device User Guide](star_citizen_user_guide.md).

### Send a profile-start message back to Companion

SC Ex includes a **Map to OSC Ex** action on **Profile Start**. It sends `/switch_sc` with no arguments to `192.168.1.95:8001`. The Companion `osc` connection listens for that path with **Listen for OSC messages (No Arguments)** feedback. To recreate the route, set the action target to your Companion computer’s address and its **Feedback Port**, then match the path in the Companion feedback. [Send feedback to a panel](#send-feedback-to-a-panel)

## Test a button from the same PC

Create a **Button** input with address `/gex/test/button`. Add **Play Sound/TTS** with a short sound and enable **Execute on press** only. Save and activate the profile. Send an OSC integer `1` and then `0` from your panel, or run this Python 3 example. Replace the IP and port with the values in **Options → OSC/MIDI**.

```python
import socket
import struct
import time


def osc_string(value):
    data = value.encode("ascii") + b"\0"
    return data + b"\0" * (-len(data) % 4)


destination = ("127.0.0.1", 8000)
header = osc_string("/gex/test/button") + osc_string(",i")
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
    sender.sendto(header + struct.pack(">i", 1), destination)
    time.sleep(0.2)
    sender.sendto(header + struct.pack(">i", 0), destination)
```

You should hear the sound once. The input should return to released when the second message arrives. [Play Sound/TTS User Guide](../actions/play_sound_user_guide.md)

## Import several inputs

Click **Import** on the **OSC** tab and paste one address per line. Use `B` for a button, `BNP` for an autorelease button, `A` for an axis, or `C` for Change. An address without a suffix defaults to a button.

```text
/panel/lights B
/panel/gear/pulse BNP
/panel/throttle A
/panel/selector C
```

Import adds input definitions to the selected mode. Add actions to the resulting rows and save the profile.

## Send feedback to a panel

To drive a panel indicator from a GEX mapping, add **Map to OSC Ex** to the source control. Set **Target IP** and **Target Port** to the panel’s OSC listener. Enter its address in **Command**, use **Add Argument** for the value it expects, then click **Test** and check the panel. Use a separate feedback address if the panel echoes updates back to GEX. [OSC actions](../actions.md#map-to-osc)

## Troubleshooting

| Symptom | Check |
| --- | --- |
| The OSC tab is missing | Check **Options → Modules → OSC** and restart GEX. Also check the device visibility filter. |
| The listener captures nothing | Check the sender’s destination against the IP and port shown by the listener. Use UDP, check the firewall for a LAN sender, and make sure another program has not taken that IP and port. |
| Capture works but the action does nothing | Activate the profile in the mode containing the mapping. Check the address, selected argument, action mode, and press/release settings. |
| A button stays pressed | Send a zero value to release it, or use autorelease for a sender that only sends pulses. |
| The fader never reaches center or the endpoints | Check the selected argument and configure the sender to output `0.0` through `1.0`. |

To log incoming addresses and arguments, turn on **Enable Verbose Log Mode** and **OSC** under **Options → Verbosity**, then restart GEX and check `system.log`. [Log file location](../usage.md#log-file)
