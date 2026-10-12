# -*- coding: utf-8; -*-
#
# Modal host for the standard JG Ex mapping widget (overlay button or OCR rule).

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

import gremlin.input_item
from gremlin.input_types import InputType

from .overlay_input import OverlayInputItem, ensure_overlay_input
from .model import ocr_rule_input_id, widget_display_name


class OverlayMappingDialog(QtWidgets.QDialog):
    """Embeds InputItemMappingWidget for an overlay button or OCR rule."""

    def __init__(self, widget: dict, parent=None, *, rule: dict | None = None):
        super().__init__(parent)
        self._widget = widget
        self._rule = rule if isinstance(rule, dict) else None

        if self._rule is not None:
            rule_name = str(self._rule.get("name") or self._rule.get("display_name") or "Rule")
            self.setWindowTitle(f"Overlay · OCR · {rule_name}")
            input_id = ocr_rule_input_id(str(widget.get("id") or ""), str(self._rule.get("id") or ""))
            title = f"OCR · {rule_name}"
        else:
            self.setWindowTitle(f"Overlay · Button · {widget_display_name(widget)}")
            input_id = str(widget.get("id") or "")
            title = widget_display_name(widget)

        self.setModal(True)
        self.setMinimumSize(900, 600)
        self.resize(960, 680)

        item = ensure_overlay_input(input_id, title)
        if item is None:
            raise RuntimeError("Unable to create overlay mapping (no profile loaded).")
        if not isinstance(item, OverlayInputItem):
            raise TypeError("overlay mapping item is not an OverlayInputItem")

        # Restore persisted XML onto the input before editing.
        xml = ""
        if self._rule is not None:
            xml = str(self._rule.get("mapping_xml") or "")
        else:
            xml = str(widget.get("mapping_xml") or "")
        if xml:
            from .overlay_input import apply_overlay_mapping_xml

            apply_overlay_mapping_xml(input_id, title, xml)

        layout = QtWidgets.QVBoxLayout(self)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        mapping = gremlin.input_item.InputItemMappingWidget(
            item,
            input_type=InputType.JoystickButton,
            object_name=f"OverlayMapping:{item.widget_id}",
            parent=scroll,
        )
        mapping.redraw(force=True)
        scroll.setWidget(mapping)
        mapping.redraw(force=True)
        layout.addWidget(scroll, 1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._input_item = item
        self._mapping = mapping

    def accept(self):
        from .overlay_input import (
            apply_overlay_mapping_xml,
            dump_overlay_mapping_xml,
            write_ocr_rule_mapping_xml,
            write_widget_mapping_xml,
        )

        xml = dump_overlay_mapping_xml(self._input_item)
        if self._rule is not None:
            write_ocr_rule_mapping_xml(self._widget, self._rule, self._input_item, persist_empty=True)
            title = f"OCR · {self._rule.get('name') or self._rule.get('display_name') or 'Rule'}"
            input_id = ocr_rule_input_id(str(self._widget.get("id") or ""), str(self._rule.get("id") or ""))
        else:
            write_widget_mapping_xml(self._widget, self._input_item, persist_empty=True)
            title = widget_display_name(self._widget)
            input_id = str(self._widget.get("id") or "")
        if xml:
            apply_overlay_mapping_xml(input_id, title, xml)
        super().accept()

    @property
    def input_item(self) -> OverlayInputItem:
        return self._input_item
