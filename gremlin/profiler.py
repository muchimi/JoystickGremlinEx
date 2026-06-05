# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
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

from __future__ import annotations  # deprecated with python 3.14+
import functools
import logging

syslog = logging.getLogger("system")

_viz_installed = False
if __debug__:
    try:
        from viztracer import get_tracer

        if get_tracer() is not None:
            _viz_installed = True

    except (ImportError, AttributeError):
        # setup dummy decorators
        pass


if _viz_installed:
    # enabled
    import viztracer

    ignore_function = viztracer.ignore_function
    syslog.info("VizTracer profiling: ENABLED")

else:
    # dummy wrappers
    syslog.info("VizTracer profiling: DISABLED")

    def ignore_function(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper
