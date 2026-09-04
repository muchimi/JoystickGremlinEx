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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import gremlin
import gremlin.config
from gremlin.input_types import InputType

import gremlin.ui.ui_common
import gremlin.types
from gremlin.types import ContainerViewTypes, Interactions
from gremlin.base_profile import AbstractFunctor
from gremlin.input_item import AbstractContainer, AbstractAction, AbstractContainerWidget, InputItem, ActionSelector
from shiboken6 import Shiboken
from gremlin.worker import WorkManager, WorkTask
import logging

syslog = logging.getLogger("system")


class BasicContainerWidget(AbstractContainerWidget):
    """Basic container which holds a single action."""

    def __init__(self, input_item: InputItem, container: AbstractContainer, parent=None):
        """Creates a new instance.

        :param input_item the input item represented by this widget
        :param container the container represented by this widget
        :param parent the parent of this widget
        """
        super().__init__(input_item, container, parent, view=True)
        self.container = container
        self.input_item = input_item


    def _handle_interaction(self, widget, action):
        """Handles interaction icons being pressed on the individual actions.

        :param widget the action widget on which an action was invoked
        :param action the type of action being invoked
        """
        pass

    def _get_window_title(self):
        """Returns the title to use for this container.

        :return title to use for the container
        """
        title = "Basic: "
        if len(self.container.action_sets) > 0:
            stub = ", ".join(a.name for a in self.container.action_sets[0])
            title += stub

        return title


class BasicContainerFunctor(AbstractFunctor):
    """Executes the contents of the associated basic container."""

    def __init__(self, container, parent=None):
        super().__init__(container, parent)

    def process_event(self, event, value, extra_data=None):
        """Executes the content with the provided data.

        :param event the event to process
        :param value the value received with the event
        :return True if execution was successful, False otherwise
        """
        return True


class BasicContainer(AbstractContainer):
    """Represents a container which holds exactly one action."""

    name = "Basic"
    tag = "basic"
    hint = """This is a simple container that contains an action."""

    # input_types = [
    #     InputType.JoystickAxis,
    #     InputType.JoystickButton,
    #     InputType.JoystickHat,
    #     InputType.Keyboard
    # ]

    interaction_types = []

    functor = BasicContainerFunctor
    widget = BasicContainerWidget

    def __init__(self, parent=None, node=None, extra_data: dict = None):
        """Creates a new instance.

        :param parent the InputItem this container is linked to
        """
        super().__init__(parent, node, extra_data=extra_data)
        self._basic_container_generating_xml = False

    def _is_container_valid(self):
        """Returns whether or not this container is configured properly.

        :return True if the container is configured properly, False otherwise
        """
        return self.action_sets is not None


# Plugin definitions
version = 1
name = "basic"
create = BasicContainer
