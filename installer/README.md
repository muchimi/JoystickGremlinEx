# GremlinEx setup

`deploy.bat` builds the portable package and bundled Inno Setup installer.
Compile `GremlinEx.iss` without `/DBundledBuild` for the online release selector.

Run `deploy_installer.bat` from the repository root to build only the bundled
installer using the existing `dist\gremlinEx` package. It writes the installer
to `dist\installer`; its version comes from `dist\gremlinEx\gremlinEx.exe`.
Build the application package with `deploy.bat` first when it needs updating.
The script finds Inno Setup 6 or 7 automatically, or uses the compiler selected
with `set "ISCC_EXE=C:\path\to\ISCC.exe"`.

`deploy.bat --push` builds and uploads both artifacts. `deploy.bat --push-only`
uploads the existing artifacts for the version in `gremlin/version.py`; it fails
if that version's ZIP or installer is missing, even when older builds exist.
Run `python upload_release.py --check-assets` to check the selected files locally
without contacting GitHub.

Both installers offer unchecked tasks for optional dependencies:

- HidHide is offered when its driver/service and installer dependency registration are absent.
- GEX Maestro Bridge is offered when neither vJoy nor the bridge is installed. Detection includes the Windows services, the bridge's 32/64-bit uninstall registration, and its default console installation.

Selected installers run sequentially after GremlinEx is installed and before its launch option runs. They are independent installations: GremlinEx uninstall does not remove them. Cancellation or download/install failure leaves GremlinEx installed. Restart requests are passed back to GremlinEx setup, and automatic dependency reboots are suppressed.

Downloads use the latest stable x64 setup from the official repositories:
[HidHide](https://github.com/nefarius/HidHide/releases) and
[GEX Maestro Bridge](https://github.com/muchimi/GEXMaestroBridgeService/releases).
An Internet connection and a published setup asset are required for downloads.
HidHide device hiding and application permissions remain configured through HidHide.
Configure Maestro devices through the bridge and GremlinEx's Maestro tools after installation.

GremlinEx also checks virtual output providers at startup. Missing or unusable vJoy DLLs do not terminate the application. A connected Maestro bridge can provide virtual output instead. When neither provider is available and neither vJoy nor the bridge is installed locally, GremlinEx offers to download and install the bridge using this same helper. Declining, cancelling, or a failed installation leaves GremlinEx open with virtual joystick output unavailable. An installed but stopped or disabled bridge produces a configuration warning instead of another installation offer. Successful setup enables Maestro and attempts to connect; a requested restart is reported without restarting Windows automatically.

The bridge release must contain `GEXMaestroBridgeSetup-<version>-x64.exe`, matching the bridge project's Inno Setup output name. HidHide releases must contain `HidHide_<version>_x64.exe`. Source archives and unrelated assets are ignored; missing or ambiguous setup assets produce an optional-install failure.

Silent setup leaves optional tasks unchecked. Select them explicitly with
`/TASKS="hidhide,maestrobridge"`; selected child installers then also run silently.
The online installer's **Extract portable copy** button only extracts files (and the existing optional FFmpeg download); it does not install these system dependencies.
