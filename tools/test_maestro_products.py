"""Hardware-free checks for sequential Maestro product IDs and creation paths."""
import ast
import logging
from pathlib import Path
import re
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
source = ast.parse((ROOT / "gremlin/maestro.py").read_bytes())
names = {"gex_product_id", "gex_device_sort_key", "save_device_definition", "is_valid_gex_id", "MaestroResult"}
namespace = dict(re=re, GEX_PRODUCT_ID=1, GEX_VENDOR_ID=1, GEX_JOYSTICK_PID_BASE=0x4700,
                 GEX_GAMEPAD_PID_BASE=0x4800, GEX_MAX_DEVICES=256, MAX_GAMEPADS=4,
                 _GEX_ID_PATTERN=re.compile(r"gex-(?:gp-)?(\d+)"), syslog=logging.getLogger(__name__))
nodes = [node for node in source.body if getattr(node, "name", None) in names]
maestro = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "Maestro")
nodes.append(next(node for node in maestro.body if getattr(node, "name", None) == "deleteAll"))
exec(compile(ast.Module(body=nodes, type_ignores=[]), "gremlin/maestro.py", "exec"), namespace)
product_id = namespace["gex_product_id"]
save = namespace["save_device_definition"]
Result = namespace["MaestroResult"]


class ProductChecks(unittest.TestCase):
    def test_all_slots_have_unique_sequential_product_ids(self):
        ids = [f"gex-{n}" for n in range(1, 257)] + [f"gex-gp-{n}" for n in range(1, 5)]
        self.assertEqual([product_id(id) for id in ids], list(range(0x4701, 0x4801)) + list(range(0x4801, 0x4805)))
        self.assertEqual(len({product_id(id) for id in ids}), 260)
        for id in ("gex-0", "gex-01", "gex-257", "gex-gp-5", "other"):
            self.assertEqual(product_id(id), 1)

    def test_editor_sends_slot_product_id_independent_of_display_name(self):
        client = Mock()
        client.request.return_value = Result(True, "/maestro_create_custom")
        row = dict(id="gex-10", name="Pilot controls", kind="custom", buttons=128, axes=8, hats=4, enabled=True)
        self.assertTrue(save(client, row))
        client.request.assert_called_once_with("/maestro_create_custom", "gex-10", "Pilot controls", 128, 8, 4, 1, 0x470A)

    def test_layout_edit_retains_explicit_named_custom_identity(self):
        client = Mock()
        client.request.return_value = Result(True, "/maestro_create_custom")
        row = dict(id="named", name="Pilot controls", kind="custom", buttons=16, axes=8, hats=0,
                   enabled=True, vendorId=1, productId=0x4902)
        self.assertTrue(save(client, {k: v for k, v in row.items() if k not in ("vendorId", "productId")}, row | dict(buttons=8)))
        self.assertEqual(client.request.call_args_list[1].args,
                         ("/maestro_create_custom", "named", "Pilot controls", 16, 8, 0, 1, 0x4902))

    def test_numeric_service_order_is_independent_of_arrival_order(self):
        ids = ["gex-gp-4", "gex-16", "gex-2", "gex-gp-1", "gex-1", "gex-10"]
        self.assertEqual(sorted(ids, key=namespace["gex_device_sort_key"]),
                         ["gex-1", "gex-2", "gex-10", "gex-16", "gex-gp-1", "gex-gp-4"])

    def test_delete_all_uses_ids_across_product_families_and_preserves_other_clients(self):
        client = Mock()
        client.list.return_value = [dict(id=id) for id in ("gex-1", "gex-10", "gex-gp-4", "named", "foreign")]
        client.request.return_value = Result(True, "/maestro_delete")
        owner = NS(client=client, _controller_map={0: NS(id="named")},
                   refreshDevices=Mock(), _default_devices_prompted=False)
        self.assertTrue(namespace["deleteAll"](owner))
        self.assertEqual([call.args for call in client.request.call_args_list],
                         [("/maestro_delete", id) for id in ("gex-1", "gex-10", "gex-gp-4", "named")])
        self.assertTrue(owner._default_devices_prompted)
        owner.refreshDevices.assert_called_once_with()

    def test_empty_delete_does_not_issue_a_vendor_product_wildcard(self):
        client = Mock()
        client.list.return_value = [dict(id="foreign")]
        owner = NS(client=client, _controller_map={}, refreshDevices=Mock())
        self.assertTrue(namespace["deleteAll"](owner))
        client.request.assert_not_called()

    def test_rename_keeps_hardware_identity(self):
        client = Mock()
        client.request.return_value = Result(True, "/maestro_rename")
        row = dict(id="gex-2", name="Pilot controls", kind="custom", buttons=16, axes=8, hats=0, enabled=True)
        self.assertTrue(save(client, row, row | dict(name="Old controls")))
        client.request.assert_called_once_with("/maestro_rename", "gex-2", "Pilot controls")


if __name__ == "__main__":
    unittest.main()
