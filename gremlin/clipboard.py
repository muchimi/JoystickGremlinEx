
import dill
import base64
import os
import lxml
import logging
from PySide6 import QtCore
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QClipboard
import lxml.etree
import jsonpickle
import importlib
import msgpack


import gremlin.base_profile
from gremlin.singleton_decorator import SingletonDecorator

class ObjectEncoder():
    ''' helper class to encode objects '''
    def __init__(self, obj, data):
        cls = type(obj)
        self._name = cls.__name__
        self._module = cls.__module__
        self._data =data

    @property
    def data(self):
        return self._data
    
    @property
    def module(self):
        return self._module
    
    @property
    def name(self):
        return self._name

@SingletonDecorator
class Clipboard(QtCore.QObject):
    ''' clipboard data '''

    # occurs on clipboard changes
    clipboard_changed = QtCore.Signal(QtCore.QObject)

    def __init__(self):
        from gremlin.util import userprofile_path
        from gremlin.config import Configuration
        super().__init__()
        self._data = None
        self._enabled_count = 0

        config = Configuration()
        self._persist_to_file = config.persist_clipboard
        self._clipboard_file = os.path.join(userprofile_path(),"clipboard.data")

        #self._decode() # initialize windows clipboard data if any

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
        from gremlin.base_profile import AbstractContainer, AbstractAction
        data = None
        if self._persist_to_file:
            # see if the file exists
            if os.path.isfile(self._clipboard_file):
                # load from that
                read_ok = True
                with open(self._clipboard_file,"rb") as f:
                    try:
                        data = dill.load(f)
                    except Exception as error:
                        data = None
                        read_ok = False
                if not read_ok:
                    os.unlink(self._clipboard_file)

        else:
            try:
                pickled = self.get_windows_clipboard_text()
                if pickled:
                    try:
                        if pickled.endswith("="):
                            data = dill.loads(base64.b64decode(pickled)).encode()
                
                    except:
                        # attempt json pickle
                        data = dill.loads(pickled)

                    # validate the data is something we recognize
            except:
                # bad data - just ignore
                self.set_windows_clipboard_text(None)
                pass

        if data and isinstance(data, AbstractContainer) \
            or isinstance(data, AbstractAction):
            self._data = data



    
    @data.setter
    def data(self, value):
        import gremlin.util
        if self.enabled:
            self._data = value
            # indicate the clipboard was changed so UI can be updated
            self.clipboard_changed.emit(self)

            # persist to a temporary file
            if self._persist_to_file:
                write_ok = True
                with open(self._clipboard_file,"wb") as f:
                    try:
                        dill.dump(value, f)
                        f.flush()
                    except Exception as error:
                        write_ok = False
                        logging.getLogger("system").error(f"Unable to store clipboard data: {error}")
                if not write_ok and os.path.isfile(self._clipboard_file):
                    os.unlink(self._clipboard_file)

            
            else:
                # persist to windows clipboard
                try:
                    pickled = dill.dumps(value) # binary
                    packed = base64.b64encode(pickled).decode('ascii') # text encoded
                    self.set_windows_clipboard_text(packed)
                except Exception as error:
                        logging.getLogger("system").error(f"DILL serializationf failed: {error}")        


    def set_windows_clipboard_text(self, value):
        ''' sets the windows clipboard text '''
        # method 1
        clipboard = QApplication.clipboard()
        clipboard.clear(mode = QClipboard.Mode.Clipboard)
        if value is not None:
            clipboard.setText(value, mode = QClipboard.Mode.Clipboard)
        
        # method 2
        # win32clipboard.OpenClipboard()
        # win32clipboard.EmptyClipboard()
        # win32clipboard.SetClipboardText(value, win32clipboard.CF_TEXT)
        # win32clipboard.CloseClipboard()

    def get_windows_clipboard_text(self):
        ''' gets the windows clipboard text '''

        try:
            clipboard = QApplication.clipboard()
            return clipboard.text(mode = QClipboard.Mode.Clipboard)
        except:
            return None

        
                

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
        from gremlin.base_profile import AbstractContainer
        return self.data is not None and isinstance(self.data, AbstractContainer)
    
    @property
    def is_action(self):
        ''' true if the data item is an action '''
        from gremlin.base_profile import AbstractAction
        return self.data is not None and isinstance(self.data, AbstractAction)
    
    @property
    def is_valid(self):
        ''' true if cliboard data is valid '''
        return self.data is not None and self.is_action or self.is_container

