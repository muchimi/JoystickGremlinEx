# -*- coding: utf-8; -*-

# Based on original Joystick Gremlin work by Lionel Ott and other contributors - Joystick Gremlin Ex is (C) EMCS 2025 
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.	If not, see <http://www.gnu.org/licenses/>.


import threading


class AbortableThread(threading.Thread):
    ''' killable thread '''

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        
        import gremlin.event_handler

        eh = gremlin.event_handler.EventListener()
        eh.shutdown.connect(self.stop)
        
        #self._stop_event = threading.Event()
        self._shutdown_requested = False


    def reset(self):
        ''' reset the thread'''
        self._shutdown_requested = False

    def stop(self):
        #self._stop_event.set()
        self._shutdown_requested = True

    def stopped(self):
        return self._shutdown_requested
        #return self._stop_event.is_set()


