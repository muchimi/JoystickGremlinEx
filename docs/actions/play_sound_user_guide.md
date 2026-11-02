# Play Sound — User Guide

**Play Sound/TTS** plays an audio file or generates speech from text and plays the resulting audio. Use it for button feedback, spoken status messages, alternate announcements, or a repeating sound cue. The documentation also refers to this action as **Play Sound**.

The current action offers **Audio file**, **TTS (local)**, **AI (Edge-TTS)**, and **Stop Playback** modes. Playback uses a shared audio queue, with options for device selection, overlap, repetition, fades, silence trimming, and duplicate suppression.

## Contents

- [Play Sound — User Guide](#play-sound--user-guide)
  - [Contents](#contents)
  - [Before you start](#before-you-start)
  - [Create your first sound mapping](#create-your-first-sound-mapping)
  - [Choose a source mode](#choose-a-source-mode)
    - [Audio file](#audio-file)
    - [TTS (local)](#tts-local)
    - [AI (Edge-TTS)](#ai-edge-tts)
  - [Generate, cache, and save speech](#generate-cache-and-save-speech)
  - [Use alternate phrases and folder samples](#use-alternate-phrases-and-folder-samples)
    - [Alternate spoken phrases](#alternate-spoken-phrases)
    - [Samples from a folder](#samples-from-a-folder)
    - [Dynamic text](#dynamic-text)
  - [Choose the playback device](#choose-the-playback-device)
  - [Adjust volume, loops, fades, and trimming](#adjust-volume-loops-fades-and-trimming)
  - [Choose when the action runs](#choose-when-the-action-runs)
  - [Control overlapping and queued audio](#control-overlapping-and-queued-audio)
  - [Suppress duplicate speech](#suppress-duplicate-speech)
  - [Apply settings across the profile](#apply-settings-across-the-profile)
  - [Worked examples](#worked-examples)
    - [Play a confirmation sound](#play-a-confirmation-sound)
    - [Speak one of several acknowledgements](#speak-one-of-several-acknowledgements)
    - [Send announcements to a headset](#send-announcements-to-a-headset)
    - [Play two announcements in order](#play-two-announcements-in-order)
  - [Troubleshooting](#troubleshooting)

## Before you start

Have a profile containing the source input and an available audio output device. For Audio file mode, start with a short, known-good **WAV** file. The file picker also accepts **MP3**; WAV avoids a compressed-file decoding step and is a useful first test when playback fails or starts slowly.

The action declares support for **joystick buttons and hats**. Hat inputs need virtual-button activation directions so the action receives a pressed/released state. Other input types depend on the surrounding input configuration; do not assume the action can be added directly to every raw axis.

For an initial test, use one button, one WAV file, one playback loop, and execution on press only. Leave maximum playback duration and fades at `0`, and keep **Stop previous audio** and **Block playback** off.

## Create your first sound mapping

1. Select the profile mode and source input.
2. Add **Play Sound/TTS** to the input's action container.
3. Select **Audio file**.
4. Use the folder control beside **Sound file** to select a WAV file.
5. Enable **Use system default playback device**, or select a specific output as described below.
6. Set **Volume** to a comfortable level and **Loops** to `1`.
7. Use the play control to preview the configured audio. Its tooltip is **Generate & Play** in the speech controls.
8. Enable **Execute on press** and disable **Execute on release**.
9. Save and start the profile, then press the source button.

The preview tests the sound configuration. Runtime playback also depends on the active profile mode, enabled actions, and container/action conditions.

## Choose a source mode

| Mode | Source | Main requirement |
| --- | --- | --- |
| Audio file | An existing WAV or MP3 file. | The file remains accessible on disk. |
| TTS (local) | Text generated using an installed operating-system voice. | A working local voice; no online synthesis service is used. |
| AI (Edge-TTS) | Text generated through Edge-TTS, then converted to WAV. | A connection for new speech generation and a working FFmpeg conversion. |
| Stop Playback | Stops shared playback and clears pending audio. | No audio file. Saving/reloading this mode has a current limitation; see the behavior notes. |

### Audio file

Select an actual audio file in **Sound file**, rather than a directory. You can type a path or browse for one. The adjacent delete control clears the action's file selection; it does not delete that source file from disk.  The default file format is .WAV to minimize overhead and reduce playback latency.

The profile stores the file path, not an embedded copy of the audio. If you move or share the profile, make the referenced files available on the destination computer and update their paths where needed.

Enable **Randomize from folder** to choose samples from the selected file's containing folder. See [Samples from a folder](#samples-from-a-folder) for its selection behavior.

### TTS (local)

1. Select **TTS (local)**.
2. Enter the announcement in **Text**.
3. Choose a **Voice** under **pytts Generation Options**. Use the refresh control if the available voice list has changed.
4. Set **Rate (wpm)**. New actions use `100`; the editor accepts `50` to `300` words per minute.
5. Select **Generate**, then use the play control to preview the result.

This mode generates a reusable WAV file using the local speech engine. The voices depend on what is installed on the computer. Change the main **Volume** control to adjust how loudly the generated sample plays; generation-volume controls have a limitation described in the behavior notes.  This mode is provided for legacy compatibility reasons and is not recommended.  Please use the AI mode instead for high sound quality and rich voice options.

### AI (Edge-TTS)

1. Select **AI (Edge-TTS)**.
2. Enter the text.
3. Under **ETTS Generation Options**, filter by **Locale** and **Gender**, then choose a **Voice**. Use refresh to update the voice list.
4. Leave **Rate% (gen)** and **Pitch Offset (Hz)** at `0` for the first test.
5. Select **Generate**, wait for the result, and preview it.

**Rate% (gen)** changes speech speed during generation: `0` is the normal rate, `+100` requests twice the rate, and `-50` requests half the rate. **Pitch Offset (Hz)** adjusts the generated voice pitch. These are generation settings, separate from playback volume and timing. Retest after saving and reopening the profile; pitch persistence has a current limitation.

New Edge-TTS synthesis uses a free cloud service. GremlinEx converts all audio to the .WAV file format and caches this data so generation only occurs once if the audio is not cached for the current playback parameters.  This ensures that the cloud service is only used to generate audio once, and the audio is cross-profile, meaning that other profiles with the same TTS parameters will be shared between projects.

For an announcement that must work without new synthesis, export its generated WAV and use **Audio file** mode.

## Generate, cache, and save speech

Text, engine, voice, rate, pitch, and generation-volume settings identify a cached phrase. Reusing that phrase can reuse its generated audio. Changing those settings or the translated text can require generation again.

- **Generate** forces regeneration of the configured phrases.
- The play control generates missing audio as needed and previews the selected phrase with the playback settings.
- The save control, with tooltip **Save the audio file(s)**, exports generated WAV files. One phrase opens a file-save dialog; multiple phrases open a destination-folder dialog.
- The status area reports the result and can offer a control to open the saved file's folder.

Generated audio is kept in GremlinEx's managed sounds repository, under `sounds/managed` in its user-profile folder, with a phrase index named `phrases.xml`. It is separate from the mapping profile. Saving the profile is not the same as exporting or transferring its generated audio.

The action attempts to prepare local and Edge-TTS audio at profile activation. The application also offers **Generate TTS on load** in its **Voice (TTS)** options; enabling it can increase profile load time when speech needs generating.

**Auto Generate** is shown for speech modes, but the current activation/playback paths can generate missing audio regardless of that checkbox. Generate and preview important phrases before starting the profile when predictable trigger timing matters.

## Use alternate phrases and folder samples

### Alternate spoken phrases

Separate alternatives with vertical bars in **Text**, for example:

```text
Gear down.|Landing gear extended.|Gear is down.
```

Each nonempty segment becomes a separate phrase. A trigger chooses one phrase; it does not speak the whole list. Newlines alone are not the phrase separator used by this action.

**Multi mode** selects how speech alternatives are chosen:

| Multi mode | Behavior |
| --- | --- |
| Round Robin | Cycles through the available phrases in order. |
| Random | Makes an independent random choice on each trigger. Immediate repeats are possible. |
| Timed Random | Prefers choices not used during the randomizer's cooldown. When all choices are in cooldown, it can reuse one. |

Timed Random does not start a timer that speaks automatically. It still needs input triggers. The action creates its selection randomizer with a `10-second` cooldown; this is separate from **Suppress Duplicate Playback**.

### Samples from a folder

In Audio file mode, enable **Randomize from folder** after selecting a sample in the desired folder. The scan includes WAV and MP3 entries in that folder and does not descend into subfolders. Restart the profile after changing the folder contents to refresh the runtime list.

Folder selection uses the action's timed randomizer, preferring recently unused files where possible. The **Multi mode** radio buttons control speech alternatives; they do not change the folder-selection algorithm in this version. A trigger chooses one file, then **Loops** repeats that chosen sample rather than choosing another file for each loop.

### Dynamic text

The action substitutes `${current_mode}` with the active profile mode name before generating speech:

```text
Current mode is ${current_mode}.
```

A mode name that has not been generated before can require a new cached phrase. Test the expected modes before relying on immediate speech output.

Text is also sanitized: parenthesized content and backtick-delimited text are removed, and characters outside Windows-1252 can be replaced. Preview announcements containing non-Latin text or special symbols. Use a prepared audio file when that processing would alter the required wording.

## Choose the playback device

**Use system default playback device** is enabled for new actions. It follows the Windows default output when playback is requested, which is useful when switching between speakers and a headset.

To use a fixed endpoint:

1. Disable Use system default playback device.
2. Choose the endpoint in **Playback device**.
3. Preview the sound and confirm the correct device is audible.

The **Default** button selects the currently detected default endpoint. Use the checkbox when you want to keep following later Windows default-device changes. If a fixed endpoint cannot be found, playback can fall back to the default device; check the log and test again after reconnecting audio hardware.

**Sync All** copies the selected device setting to Play Sound actions throughout the profile. Control-clicking Default similarly applies the current default endpoint across the profile. These operations do not disable each action's follow-default checkbox, so review that checkbox on actions that must use a fixed device.

Different actions can target different endpoints. Concurrent sounds can also play through the same endpoint.

## Adjust volume, loops, fades, and trimming

| Control | New-action value | Meaning |
| --- | --- | --- |
| Volume | `100` | Playback level from `0` to `100` percent. `0` is silent. |
| Loops | `1` | Total number of sample plays, from `1` to `100`. `1` means play once. |
| Max playback (s) | `0` | Intended duration limit; `0` disables it. The current editor has a unit-conversion issue, so verify nonzero values before use. |
| Fade-in (ms) | `0` | Ramp from silence at the start of the processed sample. `0` disables the fade. |
| Fade-out (ms) | `0` | Ramp to silence at the end of the processed sample. `0` disables the fade. |
| Silence Trim | All | Remove eligible silence at both ends of the sample. |
| Threshold (dB) | `-55` | Audio below this level is considered silence. |

Fades are applied to the sample used for each loop. A fade longer than a short sample can affect its entire duration. These options process playback data; they do not rewrite the source audio file.

**Silence Trim** offers **None**, **All**, and **End**. None preserves the audio, All trims both ends, and End trims only trailing silence. Lower thresholds, such as `-60 dB`, preserve quieter material; a higher threshold can remove a quiet start or ending. If a sound disappears or loses part of a word, test with None and adjust the threshold.

The playback engine also supports a pitch-preserving playback-rate setting, separate from speech-generation rate. Its editor control is not currently placed in the visible layout; see the behavior notes rather than assuming a visible rate control is available.

## Choose when the action runs

| Trigger selection | Result |
| --- | --- |
| Execute on press only | Starts playback when the source becomes pressed. This is the default. |
| Execute on release only | Starts playback when the source is released. |
| Both | A physical press/release cycle can request playback twice. |
| Neither | Input events do not request playback. |

Releasing the source does not normally stop a clip started on press. **Loops** controls a fixed repeat count, not repetition for as long as the source remains held. Use a suitable container for repeated triggering, and account for the shared queue and stop behavior below.

## Control overlapping and queued audio

By default, playback is asynchronous and accepted requests can overlap. Repeated triggers can play multiple instances of the same sample, and the profile continues processing other mappings.

| Option | Effect |
| --- | --- |
| Stop previous audio | Stops active shared audio before this queued sample starts. It can interrupt sounds started by other Play Sound actions. |
| Block playback | Waits for this sample, including its loops, to finish before the shared audio queue processes the next request. |
| Blocking delay (ms) | Displayed as an extra pause after a blocking sound. The current playback path does not apply it. |
| Stop Playback mode | Clears pending sound events and requests a stop of active shared audio. It is not limited to one action or device. |

Block playback controls the audio queue; it does **not** make the rest of the profile wait. It also does not retroactively wait for earlier sounds that were started without blocking. A queued Stop previous audio request waits behind any blocking playback already being processed.

Stopping the profile stops shared playback. Inside a [Sequence container](../containers/sequence_user_guide.md), the action also requests a shared stop when it receives an end-of-sequence notification. Give the sequence enough duration for its clips to finish; reaching a Play Sound step alone does not wait for the audio.

Stop Playback uses the action's trigger settings, but hides the detailed options panel. Configure the trigger edge before switching to Stop Playback if you need something other than the default press trigger, and review its saving limitation below.

## Suppress duplicate speech

**Suppress Duplicate Playback** skips a TTS request when its phrase matches the immediately preceding accepted phrase and the cooldown has not expired. New actions inherit the application's suppression defaults; the configuration defaults are enabled with a `5-second` cooldown.

The cooldown control displays seconds, despite the adjacent **Delay (ms)** label in the current layout. Suppression is separate from Timed Random: randomization chooses a phrase, then duplicate suppression can reject it. It does not prevent the repetitions within one accepted Loops request, and a different intervening phrase changes which phrase counts as the last one.

Disable suppression when every trigger must be heard. For an alternate-phrase test, leave it off until selection works as expected. Audio-file requests use temporary phrase identities, so do not rely on this option as a cooldown for repeatedly triggering the same WAV file.

## Apply settings across the profile

The device **Sync All** control and the **Sync** buttons beside blocking, trimming, and duplicate suppression affect multiple Play Sound actions. Review the destination actions after using them.

The current implementation copies these fields:

| Control | What is copied to existing actions |
| --- | --- |
| Device Sync All | Stored playback-device name; the follow-default checkbox remains unchanged. |
| Blocking Sync | Blocking-delay value; the Block playback checkbox is not copied. |
| Silence Trim Sync | All/End trim flags; each action's threshold remains unchanged. |
| Duplicate-suppression Sync | Suppression enabled flag. The intended cooldown copy uses a different property, so verify and set each action's actual cooldown. |

Some Sync operations also update application defaults. Save the profile after applying changes you want to retain.

## Worked examples

### Play a confirmation sound

1. Add Play Sound/TTS to the confirmation button and select Audio file.
2. Select a short WAV file, set Volume to `60`, and Loops to `1`.
3. Use system-default output and press-only execution.
4. Leave maximum playback and fades at `0`, and leave blocking and Stop previous audio off.
5. Preview, then start the profile and test one press followed by several rapid presses.

Each accepted press requests a sound. Enable Stop previous audio if a new confirmation should replace one still playing.

### Speak one of several acknowledgements

1. Select TTS (local) or AI (Edge-TTS), then choose a voice.
2. Enter `Confirmed.|Acknowledged.|Done.` in Text.
3. Select Generate and verify that three phrases are generated.
4. Select Random under Multi mode and disable Suppress Duplicate Playback for the first test.
5. Use press-only execution and trigger several times.

One phrase plays per trigger. Choose Round Robin for an ordered cycle or Timed Random to prefer recently unused alternatives.

### Send announcements to a headset

1. Disable Use system default playback device.
2. Select the headset in Playback device.
3. Preview the sound, then change the Windows default device and preview again.
4. Keep ordinary feedback actions on the system default if they should use another output.

Check the headset connection before relying on the route: a missing fixed device can cause fallback to the default output.

### Play two announcements in order

1. Create two Play Sound/TTS actions with short clips or generated phrases.
2. Enable Block playback on the first action and keep Stop previous audio off on the second.
3. Trigger the first action, then the second.

The second queued sound waits for the first blocking clip to finish. Other profile mappings continue running. If these actions are in a Sequence container, allow enough sequence time for the audio, since the sequence's end notification can stop shared playback. Blocking delay is not currently an added pause between them.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No sound in preview | File exists; selected output available; action and Windows volume; Loops at least 1; maximum playback at 0; Silence Trim set to None for diagnosis. |
| Preview works but the input does not | Profile running; correct mode; enabled action/container; trigger edge; conditions; hat virtual-button directions. |
| Sound plays twice per button cycle | Both trigger edges enabled, duplicate mappings, or a container generating repeated events. |
| Source release does not stop the sound | Expected for a press-triggered request; playback is not tied to the source hold duration. |
| New sounds overlap | Disable overlapping through the appropriate Block playback or Stop previous audio behavior. |
| Later sound requests are delayed | A blocking clip or its loops is still running; generation or conversion may also be pending. |
| Repeated speech is missing | Suppress Duplicate Playback and its cooldown. |
| A folder sample repeats | The selection pool may be exhausted within its cooldown; reuse is then allowed. |
| Speech generation fails | Nonempty text; installed local voice, or Edge voice/network connection; FFmpeg availability/conversion; writable managed sounds folder; log details. |
| First trigger is slow | Generate and preview the phrases ahead of use, or export a static WAV. Dynamic text can require a new phrase. |
| Speech wording changes or characters disappear | Text sanitation removes parenthesized/backtick content and replaces unsupported characters. Preview the final audio. |
| Sound goes to another device | Follow-default checkbox, fixed endpoint availability, Windows default output, and fallback warning in the log. |
| A quiet sound or syllable is missing | Disable Silence Trim, then lower its threshold if trimming is needed. |
| Nonzero maximum playback cuts off too soon | The current editor has a seconds/milliseconds conversion issue. Leave it at 0 and use a prepared shorter clip. |
| Audio stops when a sequence ends | Play Sound reacts to end-of-sequence notifications by requesting a shared stop. Review sequence duration and overlapping actions. |
| A synced setting differs on another action | Review the fields actually copied by each Sync control. |

Start diagnosis with Audio file mode, a known-good WAV, default output, one loop, no fades, no duration limit, no trim, and press-only execution. Add speech generation, randomization, and queue controls after that test works.
