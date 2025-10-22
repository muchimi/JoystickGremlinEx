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
import dinput
from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.base_profile

syslog = logging.getLogger("system")
         

class ReportNodeType(enum.Enum):
    Root = 0
    Device = 1
    Mode = 2
    InputItem = 4,
    Container = 5,
    Action = 6

class ReportCell():
    def __init__(self, value, border : int = None, padding : int = None, valign : int = None ):
        self.value = value
        self.border = border
        self.padding = padding
        self.valign = valign

    def to_html(self) -> str:
        border_stub = f' BORDER="{self.border}"' if self.border is not None else ""
        valign_stub = f' VALIGN="{self.valign}"' if self.valign is not None else ""
        return f"<TD{border_stub}{valign_stub}>{self.value}</TD>"

class ReportRow():
    ''' single report cell '''
    def __init__(self, columns : int = None ):
        self.cells = {}
        self.columns = columns # automatic
        self._next_index = 0

    def to_html(self) -> str:
        tr = "<TR>"
        col = 1
        if self.cells:
            populated_list = [index for index in self.cells]
            populated_list.sort()
            for index in populated_list:
                cell = self.cells[index]
                while index > col:
                    # pad
                    tr += "<TD></TD>"
                    col += 1
                tr += cell.to_html()
        tr += "</TR>"
        return tr
    
    def addCell(self, value, border = None, padding = None, valign=None):
        if not hasattr(value, "__iter__"):
            values = [value]
        else:
            values = value
        
        index = self._next_index
        for value in values:
            cell = ReportCell(value, border, padding, valign)
            self.cells[index] = cell
            index += 1

        self._next_index = index
    
class ReportTable():
    def __init__(self):
        self.rows = []
        self.border = None
        self.padding = None
        self.cellborder = None

    def to_html(self):
        border_stub = f' BORDER="{self.border}"' if self.border is not None else ""
        valign_stub = f' VALIGN="{self.valign}"' if self.valign is not None else ""
        cellpadding_stub = f' CELLPADDING="{self.cellpadding}"' if self.cellpadding is not None else ""
        tb = f"<TABLE{border_stub}{valign_stub}{cellpadding_stub}>"
        for row in self.rows:
            tb += row.to_html()
        tb+= "</TABLE"
        return tb

        



class ReportNode(anytree.NodeMixin):
    def __init__(self, node_type : ReportNodeType = None, data = None):
        self.id = gremlin.util.get_guid()
        self.node_type = node_type
        self.data = data
        self.table = ReportTable() # HTML representation of the node
        

    def addRow(self):
        pass




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

    def _generate_table(self, rows : list | tuple):
        ''' generates an HTML table based on row data - row data can contain different data tuples as well '''
        row = rows if hasattr(rows,"__iter__") else [rows]
        if rows:
            tb = "<TABLE>"
            for row in rows:
                tr = "<TR>"
                items = row if hasattr(row,"__iter__") else [row]
                for item in items:
                    if isinstance(item, tuple):
                        # text, col span
                        td = f"<TD colspan='{item[1]}'>{item[0]}</TD>"
                    else:
                        td = f"<TD>{item}</TD>"
                tr += td
                tb += tr
            tb += "</TABLE"
            return tb
        return None


    def _get_shape_label(self, node):
        ''' gets an HTML representation of the node for display purposes, returns shape, label '''
        rows = None
        match node.node_type:
            case ReportNodeType.Device:
                # device node
                device : dinput.DeviceSummary = node.data
                # "hello\nworld |{ b |{c|<here> d|e}| f}| g | h"
                #label = f"{{ \\l Device | \\l {device.name}\n{device.device_type.name} }} | {{ \\l ID | \\l{device.device_id} }}"
                label = f"Device | {{ {{Name | {device.name}}} {{Type | {device.device_type.name} }} }} {{ ID | {device.device_id} }}"
                syslog.info(label)
                return "record", label
            
            case ReportNodeType.Mode:
                # mode node
                mode_object : gremlin.base_profile.Mode = node.data
                mode = mode_object.name
                if mode == gremlin.shared_state.master_mode:
                    mode = "Master Mode"
                label = f"Mode | {mode}"
                return "record", label
            
            case ReportNodeType.InputItem:
                input_item : gremlin.base_profile.InputItem = node.data
                label = f"{{ Input | {input_item.input_id} }} | {{ Name | {input_item.display_name}}} "
                if input_item.input_description:
                    label += f"{{Description | {input_item.input_description}}}"
                return "record", label

            case ReportNodeType.Container:
                # container node
                container : gremlin.base_profile.AbstractContainer = node.data
                label = f"Container | {container.name}"
                if container.comment:
                    label += f" | {{ {container.comment}}}"
                return "record", label

            case ReportNodeType.Action:
                # action 
                action : gremlin.base_profile.AbstractAction = node.data
                label = f"Action | {action.name}"
                if action.comment:
                    label += f" Action | {action.name} | Description | {action.comment}"
                if hasattr(action, "report_record"):
                    label += f" | {{{action.report_record()}}}"

                return "record", label
                
                

                    

        if rows:
            html = self._generate_table(rows)
            return "box", html
        return None

                

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
        g.set("size", "30!,30!") 
        g.set("rankdir", 'LR')
        g.set("nodesep", '0.8')
        g.set("ranksep", '1.5' )
        g.set("fontname","helvetica")

        
        '''
        digraph G {

        subgraph cluster_0 {
            style=filled;
            color=lightgrey;
            rankdir=LR;
            node [style=filled,shape=plaintext,fontname="Helvetica"];
            a0 -> a1 -> a2 -> a3;
        d1 [label = <
        <TABLE CELLBORDER="1" CELLSPACING="0" CELLPADDING = "0" >
        <TR>
        <TD CELLPADDING="4" VALIGN="MIDDLE">Device</TD>
        <TD  BORDER = "0" PORT="f1">
            <table BORDER="0"  CELLSPACING="0" CELLPADDING = "4" >
            <tr><td  BORDER="1" >Name 1</td><td BORDER="1" >value</td></tr>
            <tr><td  BORDER="1" >Name 2</td><td BORDER="1" >value</td></tr>
            <tr><td  BORDER="1" >Name 3</td><td BORDER="1" >value</td></tr>
            <tr><td  BORDER="1" >Name 4</td><td BORDER="1" >value</td></tr>
            </table>
        </TD>
        <TD CELLPADING ="4"  PORT="f2">right</TD></TR>
        </TABLE>>];

            
        }

        
        start -> a0;
        

        start [shape=Mdiamond];
        end [shape=Msquare];
        }
        '''
       
        #report_root = self._duplicate_tree(root)
        if root:
            # self._convert_tree(root)
            for pre, fill, node in anytree.RenderTree(root):
                fillcolor = None
                shape = "box"
                match node.node_type:
                    case ReportNodeType.Device:
                        fillcolor = "#7DC082"
                        shape, label = self._get_shape_label(node)

                    case ReportNodeType.Mode:
                        fillcolor = "#B07DC0"

                        shape, label = self._get_shape_label(node)

                    case ReportNodeType.InputItem:
                        fillcolor = "#B1C07D"
                        shape, label = self._get_shape_label(node)
                    
                    case ReportNodeType.Action:
                        shape, label = self._get_shape_label(node)

                    case ReportNodeType.Container:
                        fillcolor = "#7DB6C0"
                        shape, label = self._get_shape_label(node)

                    case ReportNodeType.Root:
                        continue

                    case _:
                        label = "ignore"
                        # continue # ignore node

                n = pydot.Node(node.id, label = label , shape=shape, fontname="Helvetica", rankdir="LR")
                n.set("rankdir","LR")
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


