import win32clipboard
import dill
import base64
import os

from PySide6 import QtCore
from gremlin.base_classes import AbstractAction, AbstractContainer
from gremlin.util import userprofile_path
import gremlin.config

from gremlin.singleton_decorator import SingletonDecorator

@SingletonDecorator
class Clipboard(QtCore.QObject):
    ''' clipboard data '''

    # occurs on clipboard changes
    clipboard_changed = QtCore.Signal(QtCore.QObject)

    def __init__(self):
        super().__init__()
        self._data = None
        self._enabled_count = 0

        config = gremlin.config.Configuration()
        self._persist_to_file = config.persist_clipboard
        self._clipboard_file = os.path.join(userprofile_path(),"clipboard.data")

        self._decode() # initialize windows clipboard data if any

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
        data = None
        if self._persist_to_file:
            # see if the file exists
            if os.path.isfile(self._clipboard_file):
                # load from that
                with open(self._clipboard_file,"rb") as f:
                    data = dill.load(f)
        else:
            try:
                win32clipboard.OpenClipboard()
                pickled = win32clipboard.GetClipboardData()
                win32clipboard.CloseClipboard()
                if pickled and pickled.endswith("="):
                    # attempt to decode data into python object
                    data = dill.loads(base64.b64decode(pickled)).encode()
                    # validate the data is something we recognize
            except:
                # bad data - just ignore
                pass

        if data and isinstance(data, AbstractContainer) or isinstance(data,AbstractAction):
            self._data = data
    
    @data.setter
    def data(self, value):
        if self.enabled:
            self._data = value
            # indicate the clipboard was changed so UI can be updated
            self.clipboard_changed.emit(self)

            # persist to a temporary file
            if self._persist_to_file:
                 with open(self._clipboard_file,"wb") as f:
                    dill.dump(value, f)
                    f.flush()

            # update the windows clipboard too
            try:
                data = dill.dumps(value)
                pickled = base64.b64encode(data).decode('ascii')

                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(pickled, win32clipboard.CF_TEXT)
                win32clipboard.CloseClipboard()
            except:
                # unable to encode
                pass

    def set_windows_clipboard_text(self, value):
        ''' sets the windows clipboard text '''
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(value, win32clipboard.CF_TEXT)
        win32clipboard.CloseClipboard()

    @property
    def enabled(self):
        ''' true if the clipboard is enabled '''
        return self._enabled_count == 0
    
    def disable(self):
        ''' pushess a disable on the stack '''
        self._enabled_count += 1
    
    def enable(self, reset = False):
        ''' enables the clipboard - pops the disabled stack'''
        if reset:
           self._enabled_count = 0
        elif self._enabled_count > 0:
            self._enabled_count -= 1

    def clear_persisted(self):
        ''' clears the persisted data on disk '''
        if os.path.isfile(self._clipboard_file):
            try:
                os.unlink(self._clipboard_file)
            except:
                pass
    
    @property
    def is_container(self):
        ''' true if the data item is a container '''
        return self.data is not None and isinstance(self.data, AbstractContainer)
    
    @property
    def is_action(self):
        ''' true if the data item is an action '''
        return self.data is not None and isinstance(self.data, AbstractAction)
    
    @property
    def is_valid(self):
        ''' true if cliboard data is valid '''
        return self.data is not None and self.is_action or self.is_container

