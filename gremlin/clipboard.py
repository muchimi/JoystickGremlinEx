import dill
import base64
import os
import logging
from PySide6 import QtCore
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QClipboard
from psygnal import Signal

# import jsonpickle
# import importlib
# import msgpack
from enum import IntEnum
import win32clipboard


from gremlin.singleton_decorator import SingletonDecorator

syslog = logging.getLogger("system")


class EncoderType(IntEnum):
    Action = 1  # single action
    Container = 2  # single container
    MultiContainer = 3  # data holds multiple containers
    ActivationCondition = 4  # data holds an activation condition group
    Condition = 5  # data holds a condition


class ObjectEncoder:
    """helper class to encode objects"""

    def __init__(self, obj, data, name, encoder_type: EncoderType):
        cls = type(obj)
        self._name = name
        self._class_name = cls.__name__
        self._module = cls.__module__
        self._data = data
        self._type: EncoderType = encoder_type

    @property
    def data(self):
        return self._data

    @property
    def module(self):
        return self._module

    @property
    def name(self):
        return self._name

    @property
    def class_name(self):
        return self._class_name

    @name.setter
    def name(self, value):
        self._name = value

    @property
    def encoder_type(self) -> EncoderType:
        return self._type


@SingletonDecorator
class Clipboard(QtCore.QObject):
    """clipboard data"""

    # occurs on clipboard changes
    clipboard_changed = Signal(QtCore.QObject)

    def __init__(self):
        from gremlin.util import userprofile_path
        from gremlin.config import Configuration

        super().__init__()
        self._data = None
        self._enabled_count = 0

        config = Configuration()
        self._persist_to_file = config.persist_clipboard
        self._clipboard_file = os.path.join(userprofile_path(), "clipboard.data")

        # self._decode() # initialize windows clipboard data if any

        # user profile path

    @property
    def data(self):
        if self.enabled:
            if not self._data:
                # see if we can use windows clipboard
                self._decode()

            if self._data:
                # internal clipboard
                return self._data
        return None

    def _decode(self):
        # external clipboard
        from gremlin.input_item import AbstractContainer, AbstractAction

        data = None
        if self._persist_to_file:
            # see if the file exists
            if os.path.isfile(self._clipboard_file):
                # load from that
                read_ok = True
                with open(self._clipboard_file, "rb") as f:
                    try:
                        data = dill.load(f)
                    except Exception:
                        data = None
                        read_ok = False
                if not read_ok:
                    os.unlink(self._clipboard_file)

        else:
            try:
                pickled = self.get_windows_clipboard_text()
                if pickled:
                    try:
                        # attempt regular pickle
                        if pickled[-1] == 61:  # .endswith("="):
                            data = dill.loads(base64.b64decode(pickled)).encode()
                    except Exception:
                        # attempt json pickle
                        try:
                            data = dill.loads(pickled)
                        except Exception:
                            pass

                    # validate the data is something we recognize
            except Exception:
                # bad data - just ignore
                self.set_windows_clipboard_text(None)
                pass

        if (
            data
            and isinstance(data, AbstractContainer)
            or isinstance(data, AbstractAction)
            or isinstance(data, ObjectEncoder)
        ):
            self._data = data

    @data.setter
    def data(self, value):
        if self.enabled:
            self._data = value
            # indicate the clipboard was changed so UI can be updated
            self.clipboard_changed.emit(self)

            # persist to a temporary file
            if self._persist_to_file:
                write_ok = True
                with open(self._clipboard_file, "wb") as f:
                    try:
                        dill.dump(value, f)
                        f.flush()
                    except Exception as error:
                        write_ok = False
                        syslog.error(f"Unable to store clipboard data: {error}")
                if not write_ok and os.path.isfile(self._clipboard_file):
                    os.unlink(self._clipboard_file)

            else:
                # persist to windows clipboard
                try:
                    pickled = dill.dumps(value)  # binary
                    packed = base64.b64encode(pickled).decode("ascii")  # text encoded
                    self.set_windows_clipboard_text(packed)
                except Exception as error:
                    syslog.error(f"DILL serializationf failed: {error}")

    def set_windows_clipboard_text(self, value: str, use_qt=False):
        """sets the windows clipboard text"""

        if value is not None:
            if use_qt:
                # method 1 - this is prone to a bunch of MIME and OLE errors due to a bug in QT
                clipboard = QApplication.clipboard()
                clipboard.clear(mode=QClipboard.Mode.Clipboard)
                clipboard.setText(value, mode=QClipboard.Mode.Clipboard)
            else:
                # method 2 - use pywin32
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(value, win32clipboard.CF_TEXT)
                win32clipboard.CloseClipboard()

    def get_windows_clipboard_text(self, use_qt=False) -> str:
        """gets the windows clipboard text"""

        if use_qt:
            try:
                clipboard = QApplication.clipboard()
                return clipboard.text(mode=QClipboard.Mode.Clipboard)
            except Exception:
                return None
        else:
            try:
                win32clipboard.OpenClipboard()
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_TEXT):
                    value = win32clipboard.GetClipboardData(win32clipboard.CF_TEXT)
                else:
                    # not text content
                    return None
                win32clipboard.CloseClipboard()
                return value
            except Exception:
                syslog.error("CLIPBOARD: failed to get text")
                return None

    @property
    def enabled(self):
        """true if the clipboard is enabled"""
        return self._enabled_count == 0

    def disable(self):
        """pushess a disable on the stack"""
        self._enabled_count += 1

    def enable(self, reset=False):
        """enables the clipboard - pops the disabled stack"""
        if reset:
            self._enabled_count = 0
        elif self._enabled_count > 0:
            self._enabled_count -= 1

    def clear_persisted(self):
        """clears the persisted data on disk"""
        if os.path.isfile(self._clipboard_file):
            try:
                os.unlink(self._clipboard_file)
            except Exception:
                pass

    @property
    def is_container(self):
        """true if the data item is a container"""
        from gremlin.input_item import AbstractContainer

        data = self.data
        if isinstance(data, ObjectEncoder):
            return data.encoder_type in (
                EncoderType.Container,
                EncoderType.MultiContainer,
            )
        return self.data is not None and isinstance(self.data, AbstractContainer)

    @property
    def is_action(self):
        """true if the data item is an action"""
        from gremlin.base_profile import AbstractAction

        data = self.data
        if isinstance(data, ObjectEncoder):
            return data.encoder_type == EncoderType.Action
        return self.data is not None and isinstance(self.data, AbstractAction)

    @property
    def is_valid(self):
        """true if cliboard data is valid"""
        return self.data is not None and self.is_action or self.is_container
