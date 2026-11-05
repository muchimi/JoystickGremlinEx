
# GEX Command-line options (m77T91+)

GremlinEx (GEX) can be started with command line switches (arguments) provided to the executable.  These switches can alter options on the fly without configuring the application via its options panel.

## Behavior

Command-line options are by default temporary and affect the current session only.  Add `/persist` to save the supplied option values as defaults for future launches.

Options not supplied on the command line are left unchanged.

Module switches let you enable or disable certain GEX features.  It's important that if a profile is using a disabled feature, the relevant profile sections wil be ignored, but a subsequent save of the profile may result in the loss of data because the relevant modules to process this data are not loaded.

## Format

Options use slash (Windows style) prefixes or dash (Python style) prefixes. The aliases listed below are equivalent.

## List of supported options

| Option | Description |
| --- | --- |
| `/no-profile`, `/np` | Start without loading a profile. This also prevents automatic profile start. With `/persist`, disables loading the last-used profile by default on future launches. |
| `/profile <file.xml>`, `/p <file.xml>` | Load the specified profile. If the file is not found at the given path, GremlinEx looks for it in its data folder. A profile XML path can also be supplied without this option. With `/persist`, the selected profile becomes the last-used profile for future launches. |
| `/mousehook`, `/mh` | Enable the mouse hook (diagnostics use only). |
| `/no-mousehook`, `/no-mh`, `--no-mousehook` | Disable the mouse hook. |
| `/as`, `/autoswitch` | Enable automatic profile switching based on mapped processes. |
| `/no-as`, `/no-autoswitch`, `--no-as`, `--no-autoswitch` | Disable automatic profile switching based on mapped processes. |
| `/autoload`, `/al` | Load the last-used profile on startup. |
| `/no-autoload`, `/no-al`, `--no-autoload` | Do not load the last-used profile on startup. |
| `/r`, `/run` | Automatically start the loaded profile, if available. |
| `/nr`, `/no-r`, `/no-run`, `--no-r`, `--no-run` | Do not automatically start the loaded profile. |
| `/voice`, `/v` | Enable the voice recognition module. |
| `/no-voice`, `/no-v`, `--no-voice` | Disable the voice recognition module. |
| `/overlay`, `/ov` | Enable the overlay module. |
| `/no-overlay`, `/no-ov`, `--no-overlay` | Disable the overlay module. |
| `/streamdeck`, `/sd` | Enable the Stream Deck module. |
| `/no-streamdeck`, `/no-sd`, `--no-streamdeck` | Disable the Stream Deck module. |
| `/osc` | Enable the OSC (Open Stage Control) module. |
| `/no-osc`, `--no-osc` | Disable the OSC module. |
| `/midi` | Enable the MIDI module. |
| `/no-midi`, `--no-midi` | Disable the MIDI module. |
| `/theme dark`, `/theme light`, `/theme auto` | Set the application theme. |
| `/min`, `/m` | Start the application minimized to the tray. |
| `/no-min`, `--no-min` | Do not start the application minimized. |
| `/persist` | Save the supplied command-line option values as defaults for future launches. |
| `/help`, `/h`, `/?` | Show command-line help and exit. |

## Examples

Start with voice recognition disabled for this session:

```text
gremlinex.exe /no-voice
```

Load a profile and automatically start it for this session:

```text
gremlinex.exe /profile "C:\Profiles\Example.xml" /run
```

Save the selected theme and module settings for future launches:

```text
gremlinex.exe /theme dark /voice /persist
```
