"""HidHide IOCTL and bulk selection tests with no driver writes."""

from contextlib import nullcontext
import unittest
from unittest.mock import call, patch

from gremlin import hidhide


class HidHideTests(unittest.TestCase):
    def test_startup_access_check_honors_inverse_mode_without_device_enumeration(self):
        image = r"\Device\HarddiskVolume3\GremlinEx.exe"
        for listed, inverse, allowed in ((True, False, True), (False, False, False), (True, True, False), (False, True, True)):
            with self.subTest(listed=listed, inverse=inverse), \
                 patch.object(hidhide, "_control_device", return_value=nullcontext(42)), \
                 patch.object(hidhide, "_process_image", return_value=image), \
                 patch.object(hidhide, "_multi_sz", return_value={image.casefold(): image} if listed else {}), \
                 patch.object(hidhide, "_flag", return_value=inverse), \
                 patch.object(hidhide, "_enumerate_devices") as enumerate_devices:
                self.assertEqual(hidhide.HidHide().gex_allowed(), allowed)
                enumerate_devices.assert_not_called()

    def test_reads_configuration_and_keeps_unplugged_hidden_entries(self):
        device = r"HID\VID_045E&PID_02FF\GAMEPAD"
        parent = r"USB\VID_045E&PID_02FF\GAMEPAD"
        unplugged = r"HID\VID_1234&PID_0001\UNPLUGGED"
        hidden = {parent.casefold(): parent, unplugged.casefold(): unplugged}
        image = r"\Device\HarddiskVolume3\GremlinEx.exe"
        interfaces = [(device, "interface", True, "Xbox controller", True, parent, (parent,), True)]
        with patch.object(hidhide, "_control_device", return_value=nullcontext(42)), \
             patch.object(hidhide, "_process_image", return_value=image), \
             patch.object(hidhide, "_multi_sz", side_effect=[hidden, {image.casefold(): image}]), \
             patch.object(hidhide, "_flag", side_effect=[True, False]), \
             patch.object(hidhide, "_enumerate_devices", side_effect=lambda paths: hidhide._device_rows(interfaces, {}, paths)):
            snapshot = hidhide.HidHide().read()
        self.assertTrue(snapshot.active)
        self.assertTrue(snapshot.gex_allowed)
        self.assertEqual(snapshot.hidden, {parent.casefold(): parent, unplugged.casefold(): unplugged})
        self.assertEqual(snapshot.devices[0].paths, (device, parent))
        self.assertEqual(snapshot.devices[0].apis, ("XInput",))
        self.assertEqual(snapshot.devices[1].paths, (unplugged,))
        self.assertFalse(snapshot.devices[1].present)

    def test_api_labels_use_interface_identity_even_without_a_hide_alias(self):
        path = r"\\?\HID#MAESTRO#PAD#{HID}"
        interfaces = [
            (r"HID\MAESTRO\PAD", path, True, "Maestro gamepad", True, "", (), True),
            (r"HID\MAESTRO\STICK", r"\\?\HID#MAESTRO#STICK#{HID}", False, "Maestro stick", True, "", (), False),
        ]
        pad, stick = hidhide._device_rows(interfaces, {}, {}, directinput_paths={path.lower()})
        self.assertEqual(pad.apis, ("DirectInput", "XInput"))
        self.assertEqual(pad.paths, (r"HID\MAESTRO\PAD",))
        self.assertEqual(stick.apis, ())

    def test_apply_passes_only_explicit_changes_to_driver(self):
        existing = (r"HID\DEVICE\TWO", r"HID\DEVICE\EXTERNAL")
        with patch.object(hidhide, "_control_device", return_value=nullcontext(42)), \
             patch.object(hidhide, "_multi_sz", return_value={path.casefold(): path for path in existing}), \
             patch.object(hidhide, "_flag", return_value=False), \
             patch.object(hidhide, "_device_io") as ioctl:
            hidhide.HidHide().apply({r"HID\DEVICE\ONE": True, r"hid\device\two": False}, active=True, previous_active=False)
        self.assertEqual(ioctl.call_args_list, [
            call(42, hidhide.SET_BLACKLIST, hidhide._encode_multi_sz((existing[1], r"HID\DEVICE\ONE"))),
            call(42, hidhide.SET_ACTIVE, b"\x01"),
        ])

    def test_bulk_uses_exact_identity_to_keep_output_and_hide_unused_virtual(self):
        output_path = r"\\?\HID#VID_1234&PID_BEAD&COL01#VJOY#{HID}"
        input_path = r"\\?\HID#VID_1234&PID_BEAD&COL02#VJOY#{HID}"
        output = hidhide.VirtualDevice("vJoy 1", "vJoy", (0x1234, 0xBEAD), frozenset({hidhide._interface_key(output_path)}), True)
        virtual_input = hidhide.VirtualDevice("vJoy 2", "vJoy", (0x1234, 0xBEAD), frozenset({hidhide._interface_key(input_path)}), False)
        maestro = hidhide.VirtualDevice("gex-3", "Maestro", (1, 0x4703), frozenset(), False)
        virtuals = [output, virtual_input, maestro]
        for name, path, interface, ancestors, expected in (
            ("vJoy", r"HID\VID_1234&PID_BEAD\OUT", output_path, (), False),
            ("vJoy", r"HID\VID_1234&PID_BEAD\IN", input_path, (), True),
            ("vJoy", r"HID\VID_1234&PID_BEAD\UNKNOWN", "", (), False),
            ("gex-3", r"HID\GEX_DEVICE\VIRTUAL", "", (), True),
            ("Stick", r"HID\VID_2000&PID_1234\STICK", "", (), True),
            ("Xbox controller", r"HID\VID_045E&PID_02FF\PAD", "", (r"ROOT\VIGEMBUS\0000",), False),
        ):
            with self.subTest(path=path):
                row = hidhide.HidDevice(name, (path,), interface, present=True, gaming=True)
                classified = hidhide.classify_device(row, virtuals, True, ancestors)
                self.assertEqual(classified.bulk_hide, expected)
                self.assertIs(classified.is_virtual, name != "Stick")

    def test_ioctl_lists_use_byte_sizes_and_utf16_terminators(self):
        path = "HID\\DEVICE\\Joystick \u00fc"
        data = (path + "\0\0").encode("utf-16-le")
        self.assertEqual(hidhide._encode_multi_sz([path]), data)
        self.assertEqual(hidhide._encode_multi_sz([]), b"\0\0")
        with patch.object(hidhide, "_device_io", side_effect=[(b"", len(data)), (data, len(data))]) as ioctl:
            self.assertEqual(hidhide._multi_sz(42, hidhide.GET_BLACKLIST), {path.casefold(): path})
            ioctl.assert_called_with(42, 0x80016008, capacity=len(data))

    def test_allow_gex_uses_native_image_and_honors_inverse_mode(self):
        image = r"\Device\HarddiskVolume3\GremlinEx.exe"
        other = r"\Device\HarddiskVolume4\Game.exe"
        with patch.object(hidhide, "_control_device", return_value=nullcontext(42)), \
             patch.object(hidhide, "_process_image", return_value=image), \
             patch.object(hidhide, "_flag", return_value=True), \
             patch.object(hidhide, "_multi_sz", return_value={p.casefold(): p for p in (image, other)}), \
             patch.object(hidhide, "_device_io") as ioctl:
            hidhide.HidHide().allow_gex()
        ioctl.assert_called_once_with(42, hidhide.SET_WHITELIST, hidhide._encode_multi_sz([other]))


if __name__ == "__main__":
    unittest.main()
