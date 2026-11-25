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


"""Star Citizen virtual inputs backed by the game's local gRPC telemetry server.

The server is enabled by setting the environment variable GRPC_CLIENT_SERVER_ENABLED to true.
The port used by the server is 2942 on localhost (127.0.0.1).

The server is only active when the player is in the PU, not at the menu

"""

import gremlin.shared_state
from dinput import DeviceSummary
from gremlin.types import DeviceCategory, DeviceType

from .telemetry import BUTTONS, StarCitizenClient, get_client as get_device, is_button_pressed, telemetry_enabled

DEVICE_NAME = "Star Citizen"


def make_summary():
    """Describe the special device for registration and input filtering."""

    device = DeviceSummary()
    device.name = DEVICE_NAME
    device.device_guid = gremlin.shared_state.star_citizen_tab_guid
    device.device_type = DeviceType.StarCitizen
    device.device_category = DeviceCategory.Special
    device.button_count = len(BUTTONS)
    device.axis_count = 0
    device.data["button_names"] = {index: item.label for index, item in BUTTONS.items()}
    device.setButtonCallback(is_button_pressed)
    device.setConnected(True)  # The mapping tab is usable when the game is closed.
    return device


def create_tab(device, profile, mode):
    from .tab import StarCitizenDeviceTabWidget

    return StarCitizenDeviceTabWidget(device, profile, mode)
