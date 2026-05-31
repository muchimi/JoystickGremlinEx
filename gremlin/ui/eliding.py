"""eliding widgets - borrowed from superQT and PyAppKit

Elidable controls show an ellipsis on a label and line edit if too long

"""

from __future__ import annotations  # deprecated with python 3.14+
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QTextLayout
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QLineEdit


class _GenericEliding:
    """A mixin to provide capabilities to elide text (could add '…') to fit width."""

    _elide_mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight
    _text: str = ""
    # the 2 is a magic number that prevents the ellipses from going missing
    # in certain cases (?)
    _ellipses_width: int = 2
    _font = QFont()
    _width = 100

    # Public methods

    def elideMode(self) -> Qt.TextElideMode:
        """The current Qt.TextElideMode."""
        return self._elide_mode

    def setElideMode(self, mode: Qt.TextElideMode) -> None:
        """Set the elide mode to a Qt.TextElideMode."""
        self._elide_mode = Qt.TextElideMode(mode)

    def full_text(self) -> str:
        """The current text without eliding."""
        return self._text

    def setEllipsesWidth(self, width: int) -> None:
        """A width value to take into account ellipses width when eliding text.

        The value is deducted from the widget width when computing the elided version
        of the text.
        """
        self._ellipses_width = width

    @staticmethod
    def wrapText(text, width, font=None) -> list[str]:
        """Returns `text`, split as it would be wrapped for `width`, given `font`.

        Static method.
        """
        tl = QTextLayout(text, font or QFont())
        tl.beginLayout()
        lines = []
        while True:
            ln = tl.createLine()
            if not ln.isValid():
                break
            ln.setLineWidth(width)
            start = ln.textStart()
            lines.append(text[start : start + ln.textLength()])
        tl.endLayout()
        return lines

    # private implementation methods

    def _elidedText(self, width=None, font=None) -> str:
        """Return `self._text` elided to `width`."""
        fm = QFontMetrics(font or QFont())
        ellipses_width = 0
        if self._elide_mode != Qt.TextElideMode.ElideNone:
            ellipses_width = self._ellipses_width or 2
        if width is None:
            width = self._width
        tw = max(width or 0, fm.averageCharWidth() * len(self._text))
        w = max(32, tw - ellipses_width)
        if not getattr(self, "wordWrap", None) or not self.wordWrap():
            return fm.elidedText(self._text, self._elide_mode, w)

        # get number of lines we can fit without eliding
        nlines = self.height() // fm.height() - 1
        # get the last line (elided)
        text = self._wrappedText()
        last_line = fm.elidedText("".join(text[nlines:]), self._elide_mode, width)
        # join them
        return "".join([*text[:nlines], last_line])

    def _wrappedText(self) -> list[str]:
        return _GenericEliding.wrapText(self._text, self.width(), self._font or QFont())


class ElidedString(_GenericEliding):
    def __init__(self, text: str = None, width: int = 100, font=None):
        super().__init__()
        self._font = font or QFont()
        self._width = width if width is not None else 100
        if text:
            self.setText(text)

    def text(self, width=None):
        return self._elidedText(width)

    def setText(self, text: str):
        self._text = text

    @staticmethod
    def elidedText(text: str, width=None, font=None):
        es = ElidedString(text, width, font)
        return es.text()


class QElidingLabel(_GenericEliding, QLabel):
    """
    A QLabel variant that will elide text (could add '…') to fit width.

    QElidingLabel()
    QElidingLabel(parent: Optional[QWidget], f: Qt.WindowFlags = ...)
    QElidingLabel(text: str, parent: Optional[QWidget] = None, f: Qt.WindowFlags = ...)

    For a multiline eliding label, use `setWordWrap(True)`.  In this case, text
    will wrap to fit the width, and only the last line will be elided.
    When `wordWrap()` is True, `sizeHint()` will return the size required to fit
    the full text.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if args and isinstance(args[0], str):
            self.setText(args[0])

    # Reimplemented _GenericEliding methods

    def setElideMode(self, mode: Qt.TextElideMode) -> None:
        """Set the elide mode to a Qt.TextElideMode."""
        super().setElideMode(mode)
        super().setText(self._elidedText())

    def setEllipsesWidth(self, width: int) -> None:
        """A width value to take into account ellipses width when eliding text.

        The value is deducted from the widget width when computing the elided version
        of the text.
        """
        super().setEllipsesWidth(width)
        super().setText(self._elidedText())

    # Reimplemented QT methods

    def text(self) -> str:
        """Return the label's text.

        If no text has been set this will return an empty string.
        """
        return self._text

    def setText(self, txt: str) -> None:
        """Set the label's text.

        Setting the text clears any previous content.
        NOTE: we set the QLabel private text to the elided version
        """
        self._text = txt
        super().setText(self._elidedText())

    def resizeEvent(self, event: QResizeEvent) -> None:
        event.accept()
        super().setText(self._elidedText())
        super().resizeEvent(event)

    def setWordWrap(self, wrap: bool) -> None:
        super().setWordWrap(wrap)
        super().setText(self._elidedText())

    def sizeHint(self) -> QSize:
        if not self.wordWrap():
            return super().sizeHint()
        fm = QFontMetrics(self.font())
        flags = int(self.alignment() | Qt.TextFlag.TextWordWrap)
        r = fm.boundingRect(QRect(QPoint(0, 0), self.size()), flags, self._text)
        return QSize(self.width(), r.height())

    def minimumSizeHint(self) -> QSize:
        # The smallest that self._elidedText can be is just the ellipsis.
        fm = QFontMetrics(self.font())
        flags = int(self.alignment() | Qt.TextFlag.TextWordWrap)
        r = fm.boundingRect(QRect(QPoint(0, 0), self.size()), flags, "...")
        return QSize(r.width(), r.height())


class QElidingLineEdit(_GenericEliding, QLineEdit):
    """A QLineEdit variant that will elide text (could add '…') to fit width.

    QElidingLineEdit()
    QElidingLineEdit(parent: Optional[QWidget])
    QElidingLineEdit(text: str, parent: Optional[QWidget] = None)

    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if args and isinstance(args[0], str):
            self.setText(args[0])
        # The `textEdited` signal doesn't trigger the `textChanged` signal if
        # text is changed with `setText`, so we connect to `textEdited` to only
        # update _text when text is being edited by the user graphically.
        self.textEdited.connect(self._update_text)

    # Reimplemented _GenericEliding methods

    def setElideMode(self, mode: Qt.TextElideMode) -> None:
        """Set the elide mode to a Qt.TextElideMode.

        The text shown is updated to the elided version only if the widget is not
        focused.
        """
        super().setElideMode(mode)
        if not self.hasFocus():
            super().setText(self._elidedText())

    def setEllipsesWidth(self, width: int) -> None:
        """A width value to take into account ellipses width when eliding text.

        The value is deducted from the widget width when computing the elided version
        of the text. The text shown is updated to the elided version only if the widget
        is not focused.
        """
        super().setEllipsesWidth(width)
        if not self.hasFocus():
            super().setText(self._elidedText())

    # Reimplemented QT methods

    def text(self) -> str:
        """Return the label's text being shown.

        If no text has been set this will return an empty string.
        """
        return self._text

    def setText(self, text) -> None:
        """Set the line edit's text.

        Setting the text clears any previous content.
        NOTE: we set the QLineEdit private text to the elided version
        """
        self._text = text
        if not self.hasFocus():
            super().setText(self._elidedText())

    def focusInEvent(self, event: QFocusEvent) -> None:
        """Set the full text when the widget is focused."""
        super().setText(self._text)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        """Set an elided version of the text (if needed) when the focus is out."""
        super().setText(self._elidedText())
        super().focusOutEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Update elided text being shown when the widget is resized."""
        if not self.hasFocus():
            super().setText(self._elidedText())
        super().resizeEvent(event)

    # private implementation methods

    def _update_text(self, text: str) -> None:
        """Update only the actual text of the widget.

        The actual text is the text the widget has without eliding.
        """
        self._text = text
