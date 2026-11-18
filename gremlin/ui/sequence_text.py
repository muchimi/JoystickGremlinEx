"""Import and export Sequence Container definitions in the mapping editor."""

import logging
from pathlib import Path
import re

from PySide6 import QtCore, QtWidgets

from gremlin import joystick_handling, keyboard, shared_state
from gremlin.device_remap import guid_key
from gremlin.plugin_manager import ActionPlugins
from gremlin.sequence_text import SequenceText
from gremlin.types import DeviceType


_ALIASES = {
    "ctrl": "leftcontrol", "leftctrl": "leftcontrol", "rightctrl": "rightcontrol",
    "shift": "leftshift", "alt": "leftalt", "win": "leftwin",
}
syslog = logging.getLogger("system")


def _maestro_key(device):
    return device.data.get("maestro_key") or ""


def _maestro_id(device):
    key = _maestro_key(device)
    if key:
        return key.rsplit("/", 1)[-1].casefold()
    name = (device.name or "").casefold()
    return name if re.fullmatch(r"gex-(?:gp-)?[1-9][0-9]*", name) else ""


def _codec():
    from gremlin.sound import DEFAULT_PYTTS_SPEAKER

    profile = shared_state.current_profile
    filename = getattr(profile, "profile_file", None)
    folder = Path(filename).parent if filename else None

    def resolve_output(label, control, index):
        label = label.casefold()
        native = re.fullmatch(r"vjoy-(1[0-6]|[1-9])", label)
        devices = joystick_handling.virtual_device_map()
        if native:
            request = int(native[1])
            target = joystick_handling.get_output_target(request)
            if target is None:
                raise ValueError(f'Virtual output "{label}" is unavailable.')
            device = target.device
            if request in devices.get(DeviceType.VJoy, {}):
                provider, slot = DeviceType.VJoy, request
            else:
                provider, slot = device.device_type, device.virtual_id
        else:
            guid = guid_key(label)
            matches = [
                candidate for candidate in devices.get(DeviceType.Maestro, {}).values()
                if (label == _maestro_id(candidate) or label == _maestro_key(candidate).casefold()
                    or (guid is not None and guid == guid_key(candidate.device_guid)))
            ]
            if len(matches) > 1:
                raise ValueError(f'Output "{label}" is ambiguous. Use its full Maestro service address or GUID.')
            if not matches:
                raise ValueError(f'Virtual output "{label}" is unavailable.')
            device = matches[0]
            target = joystick_handling.get_output_target(device.device_guid)
            if target is None or target.kind != "maestro":
                raise ValueError(f'Maestro output "{label}" is unavailable.')
            device = target.device
            provider, slot = DeviceType.Maestro, device.virtual_id

        if control == "a":
            axis_ids = device.axis_id_map
            valid = index in axis_ids if axis_ids else index <= device.axis_count
        else:
            valid = index <= device.button_count
        if not valid:
            raise ValueError(f'Output "{label}" has no {control}{index}.')
        return provider.name, slot

    def output_label(node):
        provider = node.get("device-type", "vjoy").casefold()
        slot = node.get("virtual-id")
        if slot is None or not slot.isdecimal():
            return None
        slot = int(slot)
        if provider in ("", "vjoy"):
            return f"vjoy-{slot}" if 1 <= slot <= 16 else None
        maestro = joystick_handling.maestro_device_map()
        device = maestro.get(slot) if provider == "maestro" else None
        if device is None:
            return None
        label = _maestro_id(device)
        if label and sum(_maestro_id(candidate) == label for candidate in maestro.values()) == 1:
            return label
        return _maestro_key(device) or str(device.device_guid)

    def key_xml(name):
        normalized = name.casefold().replace(" ", "")
        key = keyboard.key_from_name(_ALIASES.get(normalized, name), validate=True) if name else None
        if key is None:
            raise ValueError(f'Unknown key "{name}".')
        return key.to_xml()

    def key_label(node):
        virtual = int(node.get("virtual-code", 0))
        if virtual > 0:
            key = keyboard.KeyMap.find_virtual(virtual)
        else:
            key = keyboard.KeyMap.find(int(node.get("scan-code", 0)), node.get("extended", "").casefold() == "true")
        return key.name if key else None

    return SequenceText(resolve_output, output_label, key_xml, key_label,
                        base_folder=folder, local_voice=DEFAULT_PYTTS_SPEAKER)


def import_sequence(parent, install, *, into_empty=False):
    """Open the editor and install the imported sequence after validation."""
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("Import Sequence Text")
    dialog.resize(680, 490)
    layout = QtWidgets.QVBoxLayout(dialog)
    prompt = (
        "Paste a definition to fill this Sequence."
        if into_empty
        else "Paste a definition to add another Sequence to this input."
    )
    layout.addWidget(QtWidgets.QLabel(prompt))
    editor = QtWidgets.QPlainTextEdit()
    editor.setPlaceholderText(
        "sequence once\n"
        "step repeat=3 repeat-delay=100ms autorelease=50ms\n"
        "    hold gex-1 b1\n"
        '    key hold "F13"\n'
        "end step"
    )
    layout.addWidget(editor)
    status = QtWidgets.QLabel()
    status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    status.setWordWrap(True)
    layout.addWidget(status)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
    preview = buttons.addButton("Check Text", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
    create = buttons.addButton(
        "Import Text" if into_empty else "Create Sequence",
        QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
    )
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    codec = _codec()

    def validate():
        plugins = ActionPlugins().tag_map
        try:
            document = codec.parse(editor.toPlainText(), action_tags=plugins)
            _validate_native_outputs(document)
        except ValueError as error:
            status.setText(str(error))
            return None
        steps = document.findall("action-set")
        def describe(action):
            name = plugins[action.tag].name
            if action.tag == "vjoyremap" and (target := codec.output_label(action)):
                name += f" → {target}"
            return name

        summary = [
            f'{index}. ' + ", ".join(describe(action) for action in step)
            for index, step in enumerate(steps, 1) if len(step)
        ]
        first_steps = "\n".join(summary[:5])
        more = f"\n… and {len(summary) - 5} more." if len(summary) > 5 else ""
        status.setText(f"{len(steps)} step(s) and {sum(len(step) for step in steps)} action(s)\n{first_steps}{more}")
        return document

    def submit():
        document = validate()
        if document is not None:
            if install(document):
                dialog.accept()
            else:
                status.setText("GEX could not load this sequence. Check the target input and the application log.")

    preview.clicked.connect(validate)
    create.clicked.connect(submit)
    editor.textChanged.connect(status.clear)
    dialog.exec()


def _validate_native_outputs(document):
    """Native imports must resolve the saved slot before the action loader runs."""
    providers = {"": DeviceType.VJoy, "vjoy": DeviceType.VJoy, "maestro": DeviceType.Maestro}
    devices = joystick_handling.virtual_device_map()
    for action in document.iter("vjoyremap"):
        provider_name = action.get("device-type", "vjoy")
        slot = int(action.get("virtual-id", "-1"))
        if slot == -1:
            identity = action.get("vjoy", "1")
            if joystick_handling.get_virtual_device(identity) is not None:
                continue
            raise ValueError(f'Native output "{identity}" is unavailable.')
        if slot not in devices.get(providers.get(provider_name.casefold()), {}):
            raise ValueError(f"Native {provider_name} slot {slot} is unavailable.")


def export_sequence(parent, container):
    """Show the sequence definition as selectable text."""
    codec = _codec()
    notes = []
    try:
        text = codec.format(container.to_xml(), notes=notes)
    except (AssertionError, AttributeError, RuntimeError, TypeError, ValueError) as error:
        syslog.exception("Unable to export sequence text")
        QtWidgets.QMessageBox.warning(parent, "Export Sequence Text", str(error) or "An action could not be saved.")
        return
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("Export Sequence Text")
    dialog.resize(760, 490)
    layout = QtWidgets.QVBoxLayout(dialog)
    editor = QtWidgets.QPlainTextEdit()
    editor.setReadOnly(True)
    editor.setPlainText(text)
    layout.addWidget(editor)
    if notes:
        visible_notes = notes[:4]
        if len(notes) > len(visible_notes):
            visible_notes.append(f"Hover to see all {len(notes)} notes.")
        notice = QtWidgets.QLabel("\n".join(visible_notes))
        notice.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        notice.setWordWrap(True)
        notice.setToolTip("\n".join(notes))
        layout.addWidget(notice)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
    copy = buttons.addButton("Copy Text", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
    copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(text))
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
