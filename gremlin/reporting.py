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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.	If not, see <http://www.gnu.org/licenses/>.



import pydot
import os
import gremlin.util
import gremlin.ui.ui_common
import gremlin.singleton_decorator
import gremlin.config
import gremlin.shared_state
import anytree
import logging
import gremlin.execution_graph as eg
import enum
from PySide6 import QtWidgets, QtCore, QtGui


syslog = logging.getLogger("system")
         

class ReportNodeType(enum.Enum):
    Root = 0
    Device = 1
    Mode = 2
    InputItem = 4,
    Container = 5,
    Action = 6

class ReportNode(anytree.NodeMixin):
    def __init__(self, node_type : ReportNodeType = None, data = None):
        self.id = gremlin.util.get_guid()
        self.node_type = node_type
        self.data = data




@gremlin.singleton_decorator.SingletonDecorator
class ReportEngine():
    ''' reporting class '''

    def __init__(self):
        # ensure installed

        # locate the graphwiz application 
        # default path: 
        
        self._graphVizInstalled = self._locate_graphviz()
        syslog.info(f"REPORT: GraphViz {'installed' if self._graphVizInstalled else 'not configured or detected'}")


    def _locate_graphviz(self):


        # see if found
        config = gremlin.config.Configuration()
        gp_exe = config.graphviz_executable
        if gp_exe and os.path.isfile(gp_exe):
            return True
        

        program_files = os.environ["ProgramFiles"]
        gp = os.path.join(program_files,"Graphviz","bin")
        if os.path.isdir(gp):
            gp_exe = os.path.join(gp, "dot.exe")
            if os.path.isfile(gp_exe):
                config.graphviz_executable = gp_exe
                return True
            
        # not found
        return False

    def get_graphviz_folder(self):
        ''' looks for the community folder '''
        config = gremlin.config.Configuration()
        gp_exe = config.graphviz_executable
        if gp_exe and os.path.isfile(gp_exe):
            initial_dir = os.path.dirname(gp_exe)
        else:
            initial_dir = os.environ["ProgramFiles"]
        
        dir = QtWidgets.QFileDialog.getExistingDirectory(
            None,
            "Select GraphViz Folder",
            dir = initial_dir
        )
        if dir and os.path.isdir(dir):
            gp_exe = os.path.join(dir, "dot.exe")
            if os.path.isfile(gp_exe):
                config.graphviz_executable = gp_exe
            return dir
        return None

    def _ensure_path(self):

        config = gremlin.config.Configuration()
        gp_exe = config.graphviz_executable
        if not os.path.isfile(gp_exe):
            return False
        
        gp = os.path.dirname(gp_exe)

        path = os.environ["PATH"]
        path = path.casefold()
        if not "graphviz" in path and os.path.isfile(gp_exe):
            path+=  os.pathsep + gp
            os.environ["PATH"] = path

        return True

    def _find_parent(self, node):
        ''' gets a parent node that is displayed '''   
        parent = node.parent
        while parent:
            if parent.nodeType in (eg.ExecutionGraphNodeType.Group,
                                   eg.ExecutionGraphNodeType.Condition,
                                   eg.ExecutionGraphNodeType.Functor,
                                   eg.ExecutionGraphNodeType.ActionSet,
                                   eg.ExecutionGraphNodeType.Functor,
                                   ):
                # skip node
                parent = node.parent
            # use it
            return parent
        return None

    def _find_action(self, node):
        ''' true if the node has an action defined in a descendant '''
        container_node = next((n for n in node.descendants if node.nodeType == eg.ExecutionGraphNodeType.Container), None)
        return container_node is not None
    
        # action_node = next((n for n in node.descendants if node.nodeType == eg.ExecutionGraphNodeType.Action), None)
        # return action_node is not None
    
    def _duplicate_node(self, node):
        nt = type(node)
        new_node = nt()
        for key, value in node.__dict__.items():
            if key in ("id", "parent", "children"):
                continue
            new_node.__dict__[key] = value # shallow copy

        return new_node

    def _duplicate_tree(self, node, new_parent = None):
        # duplicate node and writeeable properties
        new_node = self._duplicate_node(node)
        new_node.parent = new_parent
        
        for child in node.children:
            self._duplicate_tree(child, new_node)

        return new_node

    
    def _convert_tree(self, node):
        ''' converts a graph tree to a report tree '''
        
        if isinstance(node, eg.ExecutionGraphGroupNode): # or isinstance(node, eg.ExecutionGraphActionSetNode):
            # remove group, action set nodes from the tree
            parent = node.parent
            for child in node.children:
                child.parent = parent

        for child in node.children:
            self._convert_tree(child)


                

    def generate(self):
        ''' generate a map of the current profile '''
        if not self._ensure_path():
            gremlin.ui.ui_common.MessageBox(prompt ="This feature requires GraphViz.\nGraphViz could not be located.")
            return 
        


        root = ReportNode(ReportNodeType.Root)
        profile = gremlin.shared_state.current_profile

        for device in profile.devices.values():
            device_node = ReportNode(ReportNodeType.Device, data = device)
            for mode_object in device.modes.values():
                mode_node = ReportNode(ReportNodeType.Mode, data = mode_object)
                for input_type in mode_object.config.keys():
                    for input_item in mode_object.config[input_type].values():
                        input_node = ReportNode(ReportNodeType.InputItem, data = input_item)
                        if input_item.containers:
                            # mapping exists, link to the tree
                            if not device_node.parent:
                                device_node.parent = root
                            if not mode_node.parent:
                                mode_node.parent = device_node
                            input_node.parent = mode_node
                            for container in input_item.containers:
                                container_node = ReportNode(ReportNodeType.Container, data = container)
                                container_node.parent = input_node
                                for action_set in container.action_sets:
                                    for action in action_set:
                                        action_node = ReportNode(ReportNodeType.Action, data = action)
                                        action_node.parent = container_node


        g = pydot.Dot("test", graph_type="digraph")
        g.set("page", "8.5, 11")
        g.set("size", "30,30") 
        g.set("rankdir", 'LR')
        g.set("nodesep", '0.8')
        g.set("ranksep", '1.5' )

        

       
        #report_root = self._duplicate_tree(root)
        if root:
            # self._convert_tree(root)
            for pre, fill, node in anytree.RenderTree(root):
                fillcolor = None
                match node.node_type:
                    case ReportNodeType.Device:
                        fillcolor = "#7DC082"
                        label = node.data.name

                    case ReportNodeType.Mode:
                        fillcolor = "#B07DC0"
                        mode = node.data.name
                        if mode == gremlin.shared_state.master_mode:
                            mode = "Master Mode"
                        label = mode

                    case ReportNodeType.InputItem:
                        fillcolor = "#B1C07D"
                        label = node.data.display_name
      
                    
                    case ReportNodeType.Action:
                        label = str(node.data)

                    case ReportNodeType.Container:
                        fillcolor = "#7DB6C0"
                        label = node.data.name

                    case _:
                        label = "ignore"
                        # continue # ignore node
                    
                    
                n = pydot.Node(node.id, label = f"[{node.node_type.name}] {label}" , shape="box")
                if fillcolor:
                    n.set("fillcolor", fillcolor)
                    n.set("style", "filled")

                g.add_node(n)
                # parent = self._find_parent(node)
                if node.parent and node.parent != root:
                    e = pydot.Edge(node.parent.id, node.id)
                    g.add_edge(e)

            tmp_file = gremlin.util.getTemporaryFile("pdf")

            g.write_pdf(tmp_file)
            gremlin.util.display_file(tmp_file)



        # # Add nodes
        # dot.node('A', 'Node A')
        # dot.node('B', 'Node B')
        # dot.node('C', 'Node C')

        # # Add edges
        # dot.edge('A', 'B', 'Connect A to B')
        # dot.edge('B', 'C', 'Connect B to C')
        # dot.edge('A', 'C', 'Connect A to C')

        # Render and view the graph
        #dot.render('simple_graph', view=True)


