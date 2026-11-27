# Star Citizen Device User Guide

Use the **Star Citizen** device tab to turn in-game telemetry into GremlinEx (GEX) button inputs. For example, play a sound when your landing gear finishes deploying or mirror the ship lights on a control panel. If the game advertises triggerable actions, **Map to Star Citizen** sends commands back to the game.

The integration is experimental. The available telemetry fields and commands depend on the game build and the vehicle. GEX connects directly to Star Citizen’s local gRPC server at `127.0.0.1:2942`.

## Enable telemetry on Windows

1. Exit Star Citizen, close the RSI Launcher completely, including its system tray icon, and exit GEX.
2. Search Windows for **Edit environment variables for your account**. Under **User variables**, click **New** and set the variable name to `GRPC_CLIENT_SERVER_ENABLED` and the value to `true`. If the variable already exists, edit it. [Windows environment variables](https://learn.microsoft.com/en-us/windows/win32/procthread/environment-variables)
3. Reopen the RSI Launcher, start Star Citizen, and enter the pilot seat of a ship. Open GEX and select the **Star Citizen** tab.
4. If the tab is missing, check **Options → Modules → Star Citizen**, restart GEX if you changed it, and check the device visibility filter. The module is enabled by default. An explicit `GEX_STAR_CITIZEN_ENABLED=false` environment variable disables it. Remove that override or set it to `true` before starting GEX.
5. Check the status at the top of the tab. **Connected to Star Citizen (read-only telemetry)** is enough to use the inputs. **Connected to Star Citizen (telemetry and actions)** also means the server has supplied a list of commands. The vehicle label confirms GEX has received a vehicle snapshot.

The tab previews telemetry while the profile is stopped. Activate the profile to run attached mappings.

## Choose the right input

Use **Search telemetry inputs** to search by label or telemetry address. Use **Filter Inputs…** to choose which rows the tab displays. Hiding a row keeps its mappings active.

| Input | What triggers it | Example use |
| --- | --- | --- |
| **Landing gear (held while deployed)** | Presses when gear is deployed and releases when gear is retracted. It keeps the previous button state while the gear is moving. | Keep a gear indicator in sync with the ship. |
| **Landing gear — deploying** | Sends one press and release when the gear starts deploying. | Play a cue when deployment begins. |
| **Landing gear — deployed** | Sends one press and release when the gear finishes deploying. | Announce that the gear is down. |
| **Landing gear — changed** | Sends one press and release at each reported change, including the start and end of movement. | Refresh a display whenever gear state changes. |

The same patterns apply to inputs such as **Lights**, **VTOL**, and **Wing transformation** where the corresponding rows are available. Other rows cover power systems, shields, quantum spool and drive status, and master mode. The first telemetry snapshot establishes the starting state without sending change pulses. Held inputs can synchronize to that state while a profile is active. A single transition can fire both the **changed** row and a specific state row, so use one of them for a cue you want to hear once.

## Play a cue when the landing gear is down

1. With the profile stopped, select the profile mode you fly in and open the **Star Citizen** tab.
2. Search for `landing gear`, then select **Landing gear — deployed**.
3. Add a **Basic** container and a **Play Sound/TTS** action. Choose a short audio file or set up a spoken phrase. Enable **Execute on press** and disable **Execute on release**. [Play Sound/TTS User Guide](../actions/play_sound_user_guide.md)
4. Save and activate the profile. In Star Citizen, start with gear retracted, then lower it on a ship that reports gear telemetry. The cue should play once when the gear finishes deploying.

## Send a command to the game

1. Start the game and wait for **Connected to Star Citizen (telemetry and actions)**.
2. Select a source such as a joystick button or configured keyboard input. Add a **Basic** container and the **Map to Star Citizen** action.
3. Pick a command from **Game action**. The game server supplies the dropdown entries.
4. Leave **Hold duration** at `0 ms` for a normal press. Enter a duration only if the server supports holds for that command. The duration is fixed in the mapping.
5. Save and activate the profile. Press the source control in the game and verify the result.

## Troubleshooting

| What you see | What to check |
| --- | --- |
| **Set GRPC_CLIENT_SERVER_ENABLED=true to enable telemetry** | Check the Windows variable name and value, then fully restart the launcher, game, and GEX. |
| **Waiting for Star Citizen** or a gRPC error | Check that the game is running on the same PC and was started after the variable was set. GEX retries the local connection automatically. |
| **Waiting for vehicle telemetry** | Enter a pilot seat. Some fields are available only on certain ships or in certain flight states. |
| An input lights up but its action does not run | Activate the profile in the mode containing the mapping and check its conditions and press/release settings. |
| **Game action** has no options | Check the connection status. With read-only telemetry, inputs work but the server has advertised no commands. |

For more detail, open **Options → Verbosity**, turn on **Enable Verbose Log Mode**, and select **StarCitizen**. Restart GEX to capture telemetry changes in `system.log`. The tab also shows current telemetry values in this mode. [Log file location](../usage.md#log-file)
