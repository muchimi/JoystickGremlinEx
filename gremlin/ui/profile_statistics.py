# Copyright (C) 2026 EMCS (Gremlin Ex (GEX) contributions)
#
# Written for Gremlin Ex by Muchimi
# Some portions are derived from the original 2019 Joystick Gremlin by Lionel Ott and other contributors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.


"""Dialog for viewing and exporting the loaded profile's statistics."""

import ctypes
from ctypes import wintypes
from pathlib import Path

import qtawesome as qta
from PySide6 import QtCore, QtGui, QtWidgets

import gremlin.shared_state
import gremlin.util
from gremlin.profile_statistics import COUNTING_NOTE, collect_profile_statistics
from gremlin.ui.ui_common import BaseDialogUi, Color, QDataCheckbox, QDataPushButton, QDataTab, QOperationDialog, QWrapableLabel, getHContainer


def _report_page_size():
    # LOCALE_IPAPERSIZE with a null locale name reads the Windows user locale.
    # GEX sets Qt's default locale separately for the rest of the UI.
    get_locale_info = ctypes.WinDLL("kernel32").GetLocaleInfoEx
    get_locale_info.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPWSTR, ctypes.c_int]
    get_locale_info.restype = ctypes.c_int
    paper_size = ctypes.create_unicode_buffer(8)
    if get_locale_info(None, 0x100A, paper_size, len(paper_size)) and paper_size.value in ("1", "2"):
        # DMPAPER_LETTER and DMPAPER_LETTERSMALL have the same dimensions.
        return QtGui.QPageSize(QtGui.QPageSize.PageSizeId.Letter)
    return QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4)


def _write_report_pdf(path, markdown, title):
    """Print the same report as the preview using a separate print layout."""
    output = QtCore.QSaveFile(str(path))
    if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())

    writer = QtGui.QPdfWriter(output)
    writer.setTitle(title)
    writer.setCreator("Gremlin Ex")
    writer.setResolution(96)
    writer.setPageLayout(
        QtGui.QPageLayout(
            _report_page_size(),
            QtGui.QPageLayout.Orientation.Landscape,
            QtCore.QMarginsF(),
            QtGui.QPageLayout.Unit.Millimeter,
        )
    )
    document = QtGui.QTextDocument()
    document.setDefaultFont(QtGui.QFont("Segoe UI", 10))
    text = document.defaultTextOption()
    text.setWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(text)
    document.setMarkdown(markdown)
    seen_section = False
    block = document.begin()
    while block.isValid():
        style = block.blockFormat()
        if style.headingLevel() == 2:
            if seen_section and block.text() in ("Input Keybinds", "Bindings by Device"):
                style.setPageBreakPolicy(QtGui.QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
                QtGui.QTextCursor(block).setBlockFormat(style)
            seen_section = True
        block = block.next()
    for table in document.rootFrame().childFrames():
        if isinstance(table, QtGui.QTextTable):
            style = table.format()
            style.setHeaderRowCount(1)
            style.setCellPadding(4)
            last_header = table.cellAt(0, table.columns() - 1).firstCursorPosition().block().text()
            column_width = {"Mapping chain": 50, "Maps to": 65, "Condition details": 36}.get(last_header)
            if column_width is not None:
                kind = QtGui.QTextLength.Type
                widths = [QtGui.QTextLength(kind.VariableLength, 0)] * (table.columns() - 1)
                widths.append(QtGui.QTextLength(kind.PercentageLength, column_width))
                style.setWidth(QtGui.QTextLength(kind.PercentageLength, 100))
                style.setColumnWidthConstraints(widths)
            table.setFormat(style)
    document.print_(writer)
    del writer
    if not output.commit():
        raise OSError(output.errorString())


class _PercentageItem(QtWidgets.QTableWidgetItem):
    def __init__(self, value):
        super().__init__(value)
        self._percentage = float(value.rstrip("%"))

    def __lt__(self, other):
        if isinstance(other, _PercentageItem):
            return self._percentage < other._percentage
        return super().__lt__(other)


class ProfileStatisticsDialog(BaseDialogUi):
    def __init__(self, profile, parent=None):
        super().__init__("ProfileStatisticsDialog", width=740, height=570, parent=parent)
        self.setWindowTitle("Profile Statistics")
        self._statistics = collect_profile_statistics(profile, gremlin.shared_state.master_mode)
        if profile.profile_file:
            path = Path(profile.profile_file)
            self._export_path = path.with_name(f"{path.stem}-statistics.md")
        else:
            self._export_path = Path(gremlin.shared_state.data_path) / "profile-statistics.md"

        layout = QtWidgets.QVBoxLayout(self)
        name = QtWidgets.QLabel(self._statistics.name)
        name.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(getHContainer(["Profile:", name], widget_only=True))

        tabs = QDataTab()
        tabs.setStyleSheet(Color().cssTab())
        for title, headers, rows in self._statistics.sections():
            table = QtWidgets.QTableWidget(len(rows), len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.verticalHeader().hide()
            table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            for row_index, row in enumerate(rows):
                for column, value in enumerate(row):
                    is_percentage = headers[column] == "% of all mappings"
                    if is_percentage:
                        item = _PercentageItem(value)
                    else:
                        item = QtWidgets.QTableWidgetItem()
                        item.setData(QtCore.Qt.ItemDataRole.DisplayRole, value)
                    if isinstance(value, int) or is_percentage:
                        item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                    if title in ("Conditions", "Output Bindings", "State and Loopback Mappings"):
                        item.setToolTip(value)
                    table.setItem(row_index, column, item)
            header = table.horizontalHeader()
            initial_widths = {
                "Conditions": (85, 115, 85, 210),
                "Output Bindings": (160, 125, 90, 80),
            }.get(title)
            if initial_widths:
                header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
                for column, width in enumerate(initial_widths):
                    table.setColumnWidth(column, width)
            else:
                header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            stretch_column = {
                "Conditions": 4, "Devices": 2, "Mapping Usage": 1, "Output Bindings": 4, "State and Loopback Mappings": 3,
            }.get(title, 0)
            header.setSectionResizeMode(stretch_column, QtWidgets.QHeaderView.ResizeMode.Stretch)
            if title == "Mapping Usage":
                header.setSortIndicator(headers.index("% of all mappings"), QtCore.Qt.SortOrder.DescendingOrder)
            else:
                header.setSortIndicator(-1, QtCore.Qt.SortOrder.AscendingOrder)
            table.setSortingEnabled(True)
            tabs.addTab(table, title)
        layout.addWidget(tabs)

        note = QWrapableLabel(COUNTING_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        export = QDataPushButton("Export Report...", clicked=self._export)
        close = QDataPushButton("Close", clicked=self.reject)
        layout.addWidget(getHContainer([export, close], left_stretch=True, right_stretch=False, widget_only=True))

    def _export(self):
        dialog = ProfileMarkdownDialog(self._statistics, self._export_path, parent=self)
        dialog.exec()
        self._export_path = dialog.export_path
        dialog.deleteLater()


class ProfileMarkdownDialog(QOperationDialog):
    """Choose, preview and export sections from the profile report."""

    def __init__(self, statistics, export_path, parent=None):
        super().__init__("ProfileMarkdownDialog", width=860, height=620, parent=parent)
        self._statistics = statistics
        self.export_path = export_path
        self._markdown = ""
        self.setWindowTitle("Profile Report")

        self._options_group = QtWidgets.QGroupBox("Include in report")
        option_layout = QtWidgets.QHBoxLayout(self._options_group)
        self._options = {}
        for key, label in (
            ("statistics", "GEX Profile statistics"),
            ("keybinds", "Input keybinds"),
            ("bindings", "Bindings by device"),
        ):
            check = QDataCheckbox(label, checked=key == "statistics", callback=self._update_preview)
            self._options[key] = check
            option_layout.addWidget(check)
        option_layout.addStretch()
        self.content_layout.addWidget(self._options_group)

        self._preview = QtWidgets.QTextBrowser()
        self._preview.setOpenLinks(False)
        self._preview.setOpenExternalLinks(False)
        self.content_layout.addWidget(self._preview)

        self._save_button = QDataPushButton("Export Markdown...", icon=qta.icon("fa6b.markdown"), clicked=lambda: self._save("md"))
        self._pdf_button = QDataPushButton("Export PDF...", icon=qta.icon("fa6s.file-pdf"), clicked=lambda: self._save("pdf"))
        self._close_button = QDataPushButton("Close", clicked=self.reject)
        self.button_layout.addStretch()
        for button in (self._save_button, self._pdf_button, self._close_button):
            self.button_layout.addWidget(button)
        self._update_preview()

    def _update_preview(self):
        sections = {key: check.isChecked() for key, check in self._options.items()}
        self._markdown = self._statistics.to_markdown(**sections) if any(sections.values()) else ""
        self._preview.setMarkdown(self._markdown or "Select at least one report section.")
        self._update_ui()

    def _update_ui(self):
        can_export = bool(self._markdown) and not self._busy
        self._save_button.setEnabled(can_export)
        self._pdf_button.setEnabled(can_export)
        self._options_group.setEnabled(not self._busy)
        self._close_button.setEnabled(not self._busy)

    def reject(self):
        if not self._busy:
            super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def _save(self, extension):
        if self._busy or not self._markdown:
            return
        dialog = QtWidgets.QFileDialog(self)
        dialog.setWindowTitle("Export Profile Report")
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        file_type = "PDF" if extension == "pdf" else "Markdown"
        dialog.setNameFilter(f"{file_type} files (*.{extension})")
        dialog.setDefaultSuffix(extension)
        dialog.setDirectory(str(self.export_path.parent))
        dialog.selectFile(self.export_path.with_suffix(f".{extension}").name)
        if not dialog.exec():
            return
        path = Path(dialog.selectedFiles()[0])
        if path.suffix.casefold() != f".{extension}":
            QtWidgets.QMessageBox.warning(self, "Export Profile Report", f"Choose a filename ending in .{extension}.")
            return
        markdown = self._markdown
        title = self._statistics.name

        def operation():
            if extension == "pdf":
                _write_report_pdf(path, markdown, title)
            else:
                path.write_text(markdown, encoding="utf-8")
            return path

        def complete(saved_path):
            self.export_path = saved_path
            self.status_widget.setText(f"Saved {file_type} report to {saved_path}")
            if extension == "pdf":
                gremlin.util.display_file(str(saved_path))

        self._submit(operation=operation, complete=complete, message=f"Exporting {file_type} report…", request_name=f"GEX {file_type} report export")
