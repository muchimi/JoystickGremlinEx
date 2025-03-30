# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2025 
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

"""Reads hints from a CSV file and makes them available to Gremlin for use."""

import csv

from gremlin.util import resource_path

# Stores the hints and allows Gremlin to grab the ones it needs for display
hint = {}


with open(resource_path("doc/hints.csv")) as csv_stream:
    reader = csv.reader(csv_stream, delimiter=",", quotechar="\"")
    for row in reader:
        hint[row[0]] = row[1]
