
from PySide6 import QtWidgets

class QDataWidget(QtWidgets.QWidget):
    def __init__(self, data = None, parent = None):
        super().__init__(parent)
        self._data = data

       
    @property
    def data(self):
        return self._data
    
    @data.setter
    def data(self, value):
        if self._data is not None:
            pass
        self._data = value
 