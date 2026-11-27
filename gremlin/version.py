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

from gremlin.singleton_decorator import SingletonDecorator

APPLICATION_NAME = "GremlinEx"
APPLICATION_BASE = "m77T112"
APPLICATION_MAIN = "1.0ex"
APPLICATION_EXE = "gremlinex.exe"

# APPLICATION_BASE = ""
APPLICATION_VERSION = f"{APPLICATION_MAIN} ({APPLICATION_BASE})"


@SingletonDecorator
class Version:
    version = APPLICATION_VERSION
