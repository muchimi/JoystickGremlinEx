# -*- coding: utf-8; -*-

# Based on original work by (C) Lionel Ott -  (C) EMCS 2024 and other contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.



from xml.etree import ElementTree
from gremlin.util import *
from gremlin.base_conditions import *
from collections.abc import MutableSequence



class TraceableList(MutableSequence):
    ''' implements a custom list that can be traced when it changes  '''

    def __init__(self, initlist=None, callback = None):
        super().__init__()
        self.data = []
        self._callback = callback
        if initlist is not None:
            if isinstance(initlist, list):
                self.data[:] = initlist

            elif isinstance(initlist, TraceableList):
                self.data[:] = initlist.data[:]

            else:
                self.data = list(initlist)

    def __repr__(self):
        return """<{} data: {}>""".format(self.__class__.__name__, repr(self.data))

    def __lt__(self, other):
        return self.data < self.__cast(other)

    def __le__(self, other):
        return self.data <= self.__cast(other)

    def __eq__(self, other):
        return self.data == self.__cast(other)

    def __gt__(self, other):
        return self.data > self.__cast(other)

    def __ge__(self, other):
        return self.data >= self.__cast(other)

    def __cast(self, other):
        return other.data if isinstance(other, TraceableList) else other

    def __contains__(self, value):
        return value in self.data

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return self.__class__(self.data[idx])
        return self.data[idx]
        
    def __iter__(self):
        return self.data.__iter__()
    
    def __next__(self):
        return self.data.__next__()

    def __setitem__(self, idx, value):
        # optional: self._acl_check(val)
        self.data[idx] = value
        if self._callback:
            self._callback("setitem", idx, value)

    def __delitem__(self, idx):
        if self._callback:
            self._callback("delitem", idx)
        del self.data[idx]

    def __add__(self, other):
        if isinstance(other, TraceableList):
            return self.__class__(self.data + other.data)

        elif isinstance(other, type(self.data)):
            return self.__class__(self.data + other)

        return self.__class__(self.data + list(other))

    def __radd__(self, other):
        if isinstance(other, TraceableList):
            return self.__class__(other.data + self.data)

        elif isinstance(other, type(self.data)):
            return self.__class__(other + self.data)

        return self.__class__(list(other) + self.data)

    def __iadd__(self, other):
        if isinstance(other, TraceableList):
            self.data += other.data

        elif isinstance(other, type(self.data)):
            self.data += other

        else:
            self.data += list(other)

        return self

    def __mul__(self, nn):
        return self.__class__(self.data * nn)

    __rmul__ = __mul__

    def __imul__(self, nn):
        self.data *= nn
        return self

    def __copy__(self):
        inst = self.__class__.__new__(self.__class__)
        inst.__dict__.update(self.__dict__)

        # Create a copy and avoid triggering descriptors
        inst.__dict__["data"] = self.__dict__["data"][:]

        return inst

    def append(self, value):
        self.data.append(value)
        if self._callback:
            self._callback("append",value)
        

    def insert(self, idx, value):
        if self._callback:
            self._callback("insert",value)
        self.data.insert(idx, value)

    def pop(self, idx=-1):
        if self._callback:
            self._callback("pop",idx)
        return self.data.pop(idx)

    def remove(self, value):
        self.data.remove(value)

    def clear(self):
        if self._callback:
            self._callback("clear")
        self.data.clear()

    def copy(self):
        if self._callback:
            self._callback("copy")
        return self.__class__(self)

    def count(self, value):
        return self.data.count(value)

    def index(self, idx, *args):
        return self.data.index(idx, *args)

    def reverse(self):
        self.data.reverse()

    def sort(self, /, *args, **kwds):
        self.data.sort(*args, **kwds)

    def extend(self, other):
        if self._callback:
            self._callback("extend",other.data)
        if isinstance(other, TraceableList):
            self.data.extend(other.data)

        else:
            self.data.extend(other) 