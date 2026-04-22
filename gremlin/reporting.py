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


from __future__ import annotations
import graphviz
import os
import gremlin.util
import gremlin.ui.ui_common
import gremlin.singleton_decorator
import gremlin.config
import gremlin.shared_state
import gremlin.gated_handler
import anytree
import logging
import gremlin.execution_graph as eg
from gremlin.input_types import InputType
import enum
import dinput
from PySide6 import QtWidgets, QtCore, QtGui
import gremlin.base_profile
from collections import namedtuple
import gremlin.base_conditions
import traceback
import html

syslog = logging.getLogger("system")

class CellInfo():
    def __init__(self, text : str,  border : int = None, padding : int = None, align : str = None, valign : str = None ):
        self.value = text
        self.border = border
        self.padding = padding
        self.valign = valign
        self.align = align


    def toCell(self) -> ReportCell:
        cell = ReportCell(self.text, self.border, self.padding, self.valign, self.align)
        return cell



class ReportNodeType(enum.Enum):
    Root = 0
    Device = 1
    Mode = 2
    InputItem = 4,
    Container = 5,
    Action = 6,
    GateDataGate = 7,
    GateDataRange = 8,
    GateDataCondition = 9, # gate or range condition container

class ReportOptions():
    ''' reporting options '''
    def __init__(self):
        self.export_pdf = True
        self.export_svg = True
        self.open_files = True
        self.show_folder = False


class ReportCell():
    def __init__(self, index, value : str | CellInfo , border : int = None, valign : int = None, align = "LEFT", port = None):
        self.index = index # column index 0 to ...
        if isinstance(value, CellInfo):
            self.value = value.value
            self.border = value.border
            self.valign = value.valign
            self.align = value.align
            self.port = port
            return

        self.value = value
        self.border = border
        self.align = align
        self.valign = valign
        self.port = port

    def to_html(self) -> str:
        border_stub = f' BORDER="{self.border}"' if self.border is not None else ""
        align_stub =  f' ALIGN="{self.align}"' if self.align is not None else ""
        valign_stub = f' VALIGN="{self.valign}"' if self.valign is not None else ""
        port_stub = f' PORT="{self.port}"' if self.port is not None else "" # graphviz port

        # render to HTML if needed
        if hasattr(self.value,"to_html"):
            text = f"\n{self.value.to_html()}\n"
        else:
            text = self.value
        return f"<TD{border_stub}{valign_stub}{align_stub}{port_stub}>{text}</TD>\n"

class ReportRow():
    ''' single report cell '''
    def __init__(self, index : int ,  data : str | CellInfo | list[CellInfo] = None, border : int = None, padding : int = None, valign : str =None):
        ''' creates a row - data can be a list of strings or CellInfo objects '''
        self.cells = {}
        self.index = index # row index 0 to ...
        if data:
            if hasattr(data, "__iter__"):
                insert_index = index
                for item in data:
                    self.addCell(insert_index, item, border, padding, valign)
                    insert_index += 1
            else:
                self.addCell(index, item, border, padding, valign)

    def to_html(self) -> str:
        if self.cells:
            tr = "<TR>"
            cell_order = [index for index in self.cells]
            cell_order.sort()
            current_index = 0
            for cell_index in cell_order:
                # while cell_index > current_index:
                #     tr += "<TD> </TD>\n" # cannot use </TD> in DOT
                #     current_index += 1
                cell = self.cells[cell_index]
                tr += cell.to_html()
            tr += "</TR>\n"
        else:
            return "" # "<TR><TD> </TD></TR>\n"
        return tr

    def addCell(self, index : int, value : str | CellInfo, border : int = None, padding : int = None, valign : str =None):
        if not hasattr(value, "__iter__"):
            values = [value]
        else:
            values = value

        insert_index = index
        for value in values:
            cell = ReportCell(insert_index, value, border, padding, valign)
            self.cells[insert_index] = cell
            insert_index += 1

    def setCell(self, index : int, value, border = None, valign = None, port = None):
        ''' adds a cell to the row at the specified index '''
        if isinstance(value, ReportCell):
            self.cells[index] = value
        else:
            cell = ReportCell(index, value, border = border, valign = valign, port = port)
            self.cells[index] = cell


    def clear(self):
        ''' removes cells '''
        self.cells.clear()

class ReportTable():
    def __init__(self, border : int = 0, cellpadding : int = 0, cellborder : int = 1, cellspacing = 0, bgcolor = None):
        self.rows = {}
        self.border = border
        self.cellpadding = cellpadding
        self.cellborder = cellborder
        self.cellspacing = cellspacing
        self.bgcolor = bgcolor

    def to_html(self):
        border_stub = f' BORDER="{self.border}"' if self.border is not None else ""
        cellborder_stub = f' CELLBORDER="{self.cellborder}"' if self.cellborder is not None else ""
        cellpadding_stub = f' CELLPADDING="{self.cellpadding}"' if self.cellpadding is not None else ""
        cellspacing_stub = f' CELLSPACING="{self.cellspacing}"' if self.cellspacing is not None else ""
        bgcolor_stub = f' BGCOLOR="{self.bgcolor}"' if self.bgcolor is not None else ""
        tb = f"<TABLE{border_stub}{cellborder_stub}{cellpadding_stub}{cellspacing_stub}{bgcolor_stub}>\n"


        # assume a sparse matrix of rows if they are not continuous
        row_order = [index for index in self.rows]
        row_order.sort()

        for row_index in row_order:
            # while row_index > current_index:
            #     # pad rows
            #     tb += "<TR><TD> </TD></TR>\n" # cannot use </TR> in DOT or have blanks
            #     current_index += 1
            row = self.rows[row_index]
            tb += row.to_html()
        tb+= "</TABLE>\n"
        return tb

    def addRow(self, index : int,  data : list[object | list[CellInfo] | list[object]] = None,  border : int = None, padding : int = None, valign : str =None):
        if hasattr(data,"__iter__"):
            # rows and cells
            values = data
        else:
            # single cell
            values = [data]

        current_index = index
        for item in values:
            row = ReportRow(index, item, border, padding, valign)
            self.rows[current_index] = row
            current_index += 1

    def addField(self, field_name  : str, value : str, border = 1, valign = "TOP", port = None):
        ''' adds a field - two cells - in a row
        :param field_name : first cell name
        :param value : second cell
        :param index : optional, index - if not provided, automatic

        '''
        if self.rows:
            index = len(self.rows)
        else:
            index = 0
        row = ReportRow(index)
        cell1 = ReportCell(0,field_name, border = border, valign=valign, port = port)
        cell2 = ReportCell(1,value, border = border, valign = valign)
        row.setCell(0,cell1)
        row.setCell(1,cell2)

        self.rows[index] = row

    def setCell(self, row : int, col : int, cell, border = 1, valign = "TOP", port = None):
        ''' sets a specific cell in the table'''
        row_object : ReportRow
        if row in self.rows:
            row_object = self.rows[row]
        else:
            row_object = ReportRow(row)
            self.rows[row] = row_object

        row_object.setCell(col, cell, border, valign, port)




    def clear(self):
        ''' removes rows'''
        self.rows.clear()


class ReportNode(anytree.NodeMixin):
    def __init__(self, node_type : ReportNodeType = None, data = None):
        self.id = gremlin.util.get_guid()
        self.node_type = node_type
        self.data = data
        self.table = ReportTable() # HTML representation of the node


    def addRow(self, index, data : list[str | list[CellInfo] | list[str]] = None,  border : int = None, padding : int = None, valign : str =None):
        ''' adds a data row - row data is a list of cells'''
        self.table.addRow(index, data, border, padding, valign)

    def clear(self):
        ''' removes all rows '''
        self.table.clear()





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


    def _get_shape_label(self, node) -> tuple:
        ''' gets an HTML representation of the node for display purposes, returns shape, label, fillcolor '''

        rows = None

        match node.node_type:
            case ReportNodeType.Device:
                # device node
                device : dinput.DeviceSummary = node.data

                table = ReportTable()
                device_table = ReportTable(cellpadding=4) # cell 1
                info_table = ReportTable(cellpadding=4) # cell 2

                device_table.addField("Name", html.escape(device.name))
                device_table.addField("Type", device.device_type.name)

                # syslog.info("DEVICE TABLE:")
                # syslog.info(device_table.to_html())


                info_table.addField("ID", device.device_id)
                info_table.addField("Mappings", f"{len(node.children):,}")


                table.setCell(0,0, device_table)
                table.setCell(0,1, info_table)

                label = f"<{table.to_html()}>"
                #syslog.info(label)
                return "none", label



            case ReportNodeType.Mode:
                # mode node
                mode_object : gremlin.base_profile.Mode = node.data
                mode = mode_object.name
                if mode == gremlin.shared_state.master_mode:
                    mode = gremlin.shared_state.master_mode_name

                table = ReportTable(cellpadding=4)
                table.addField("Mode",html.escape(mode))

                # add parent nodes:
                # profile = gremlin.shared_state.profile
                # ancestors = profile.getModeHierarchy(mode_object.name)

                label = f"<{table.to_html()}>"
                return "none", label

            case ReportNodeType.InputItem:
                input_item : gremlin.base_profile.InputItem = node.data


                table = ReportTable(cellpadding=4)
                table.addField("Input", str(input_item.input_id))
                table.addField("Name", html.escape(input_item.display_name))

                if input_item.input_description:
                    table.addField("Description", html.escape(input_item.input_description))

                if hasattr(input_item,"to_html"):
                    text = input_item.to_html()
                    table.addField(" ", text)

                if hasattr(input_item.input_id,"to_html"):
                    text = input_item.input_id.to_html()
                    table.addField(" ", text)


                label = f"<{table.to_html()}>"
                return "none", label

            case ReportNodeType.Container:
                # container node
                container : gremlin.base_profile.AbstractContainer = node.data


                table = ReportTable(cellpadding=4)
                table.addField("Container", container.name)

                if container.comment:
                    table.addField("Description", html.escape(container.comment))

                if container.has_conditions:
                    ct = ReportTable(cellpadding=4, bgcolor = "#C79AD4")
                    ct.addField("Count", f"{len(container.activation_condition.conditions)}")
                    for index, condition in enumerate(container.activation_condition.conditions):
                        if hasattr(condition,"to_html"):
                            ct.addField(f"C{index}", condition.to_html())
                    table.addField("Conditions", ct.to_html())

                if hasattr(container,"to_html"):
                    text = container.to_html()
                    table.addField(" ", text)

                label = f"<{table.to_html()}>"
                return "none", label

            case ReportNodeType.Action:

                # action
                action : gremlin.base_profile.AbstractAction = node.data


                table = ReportTable(cellpadding=4)
                table.addField("Action", action.name)
                if action.data and isinstance(action.data, str):
                    table.addField("Data", action.data)

                if action.comment:
                    table.addField("Description", html.escape(action.comment))

                if action.has_conditions:
                    ct = ReportTable(cellpadding=4, bgcolor = "#C79AD4")
                    ct.addField("Count", f"{len(action.activation_condition.conditions)}")
                    for index, condition in enumerate(action.activation_condition.conditions):
                        if hasattr(condition,"to_html"):
                            ct.addField(f"C{index}", condition.to_html())

                    table.addField("Conditions", ct.to_html())

                if hasattr(action, "to_html"):
                    text = action.to_html()
                    table.addField(" ", text)


                label = f"<{table.to_html()}>"
                return "none", label

            case ReportNodeType.GateDataGate:
                # gate node for gated axis
                gate : gremlin.gated_handler.GateInfo = node.data
                table = ReportTable(cellpadding=4)
                table.addField("Gate", gate.gate_display())

                label = f"<{table.to_html()}>"
                return "none", label

            case ReportNodeType.GateDataRange:
                # gate node for gated axis
                rng : gremlin.gated_handler.RangeInfo = node.data
                table = ReportTable(cellpadding=4)
                table.addField("Range", rng.to_display())

                label = f"<{table.to_html()}>"
                return "none", label

            case ReportNodeType.GateDataCondition:
                # gate crossing condition
                table = ReportTable(cellpadding=4)
                table.addField("Condition", node.data)
                label = f"<{table.to_html()}>"
                return "none", label





        if rows:
            text = self._generate_table(rows)
            return "box", text
        return None


    def generate_input_item(self, input_item, parent):
        input_node = ReportNode(ReportNodeType.InputItem, data = input_item)
        input_node.parent = parent
        if input_item.containers:
            # mapping exists, link to the tree

            for container in input_item.containers:
                container_node = ReportNode(ReportNodeType.Container, data = container)
                container_node.parent = input_node
                for action_set in container.action_sets:
                    for action in action_set:
                        action_node = ReportNode(ReportNodeType.Action, data = action)
                        action_node.parent = container_node

                        if action.tag == "gated-axis":
                            # special handling for gated axis
                            gate_data :  gremlin.gated_handler.GateData = action.gate_data
                            gate : gremlin.gated_handler.GateInfo
                            for gate in gate_data.getGates():
                                gate_node = ReportNode(ReportNodeType.GateDataGate, data = gate)
                                gate_node.parent = action_node

                                # gate containers
                                for condition, item in gate.item_data_map.items():
                                    condition_node = ReportNode(ReportNodeType.GateDataCondition, data = condition.name)
                                    condition_node.parent = gate_node
                                    self.generate_input_item(item, condition_node)

                            rng : gremlin.gated_handler.RangeInfo
                            for rng in gate_data.getRanges():
                                range_node = ReportNode(ReportNodeType.GateDataRange, data = rng)
                                range_node.parent = action_node

                                # gate containers
                                for condition, item in rng.item_data_map.items():
                                    condition_node = ReportNode(ReportNodeType.GateDataCondition, data = condition.name)
                                    condition_node.parent = range_node
                                    self.generate_input_item(item, condition_node)


    def generate(self, options : ReportOptions):
        ''' generate a map of the current profile '''
        if not self._ensure_path():
            gremlin.ui.ui_common.MessageBox(prompt ="This feature requires GraphViz.\nGraphViz could not be located.")
            return

        # current profile
        profile = gremlin.shared_state.current_profile



        root = ReportNode(ReportNodeType.Root)



        for device in profile.devices.values():
            device_node = ReportNode(ReportNodeType.Device, data = device)


            # special handling of state device
            if device.device_type == gremlin.types.DeviceType.State:
                # state device (modeless) - special handling of state input items
                state_data = gremlin.shared_state.current_profile.state
                input_items = [state_data[key].input_item for key in state_data]
                if input_items:
                    device_node.parent = root
                    mode_object = gremlin.base_profile.Mode(device)
                    mode_object.name = gremlin.shared_state.master_mode_name
                    mode_node = ReportNode(ReportNodeType.Mode, data = mode_object)
                    mode_node.parent = device_node
                for input_item in input_items:
                    self.generate_input_item(input_item, mode_node)


            else:
                # non state device
                for mode_object in device.modes.values():
                    mode_node = ReportNode(ReportNodeType.Mode, data = mode_object)
                    for input_type in mode_object.config.keys():
                        for input_item in mode_object.config[input_type].values():
                            if input_item.containers:
                                if not device_node.parent:
                                    device_node.parent = root
                                if not mode_node.parent:
                                    mode_node.parent = device_node
                                self.generate_input_item(input_item, mode_node)




        cluster_entries = {} # clusters keyed by cluster index
        node_entries = {} # nodes keyed by cluster index
        edge_entries = {} # edges keyed by cluster index

        cluster_index = 0 # cluster number - one cluster per device
        current_cluster = 0


        #report_root = self._duplicate_tree(root)
        if root:
            # self._convert_tree(root)
            for pre, fill, node in anytree.RenderTree(root):
                fillcolor = None
                shape = "box"
                match node.node_type:
                    case ReportNodeType.Device:
                        fillcolor = "#7DC082"

                        # device starts a new cluster
                        cluster = f'''
                        subgraph cluster_{cluster_index} {{
                            style=filled;
                            color=lightgrey;
                            rankdir=LR;
                            node [style=filled,shape=plaintext,fontname="Helvetica"];
                        '''

                        current_cluster = cluster_index
                        cluster_entries[current_cluster] = cluster
                        node_entries[current_cluster] = []
                        edge_entries[current_cluster] = []

                        cluster_index += 1

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

                    case ReportNodeType.GateDataGate:
                        fillcolor = "#AEABD3"
                        shape, label = self._get_shape_label(node)

                    case ReportNodeType.GateDataRange:
                        fillcolor = "#8083B4"
                        shape, label = self._get_shape_label(node)

                    case ReportNodeType.GateDataCondition:
                        fillcolor = "#ABC6D3"
                        shape, label = self._get_shape_label(node)

                    case ReportNodeType.Root:
                        continue

                    case _:
                        label = f"ignore: {node.node_type.name}"
                        # continue # ignore node

                node_entry = f'"{node.id}" [label = {label}, shape= "{shape}", fillcolor = "{fillcolor}"];\n'
                node_entries[current_cluster].append(node_entry)

                if node.parent and node.parent != root:
                    edge_entry = f'"{node.parent.id}" -> "{node.id}";\n'
                    edge_entries[current_cluster].append(edge_entry)


        #raw_file = gremlin.util.getTemporaryFile("raw")
        dot_file = gremlin.util.getTemporaryFile("dot")


        # create the DOT file
        with open(dot_file,"w",encoding = 'utf-8',errors="replace") as f:
            # DOT header
            f.write("digraph G {\n")
            f.write(f'graph [ label = "Profile Mappings for {profile.name}"\n')
            f.write("labelloc = t\n")
            f.write("fontsize = 20\n")
            f.write("layout = dot\n")
            f.write("rankdir = LR\n")
            f.write("newrank = true\n")
            f.write("]\n")
            f.write('page="8.5, 11";\n')
            f.write('size="36,36!";\n')
            f.write("rankdir=LR;\n")
            f.write("nodesep=0.8;\n")
            f.write("ranksep=1.5;\n" )
            f.write('fontname="Helvetica,Arial,sans-serif";\n')
            #f.write("edge [minlen=2];")

            for index in cluster_entries:
                f.write(cluster_entries[index])
                # write nodes
                f.writelines(node_entries[index])
                # write edges
                f.writelines(edge_entries[index])

                f.write("\n}\n")

            # close digraph
            f.write("\n}\n")

            f.flush()
            f.close()

        # # filter out any offending character as the DOT file has to be in UTF-8 format
        # with open(raw_file,'r', encoding='utf-8', errors='xmlcharrefreplace') as fin:
        #     content = fin.read()
        # with open(dot_file, 'w', encoding='utf-8') as fout:
        #     fout.write(content)
        #     fout.flush()
        #     fout.close()
        # os.unlink(raw_file)


        # g.write_dot(dot_file)
        syslog.info(f"DOT FILE:")
        syslog.info(dot_file)




        try:

            # get a report file matching the profile
            file_base, _ = os.path.splitext(profile.profile_file)

            if options.export_pdf:
                pdf_file = gremlin.util.next_file(file_base + ".pdf", False)
                s = graphviz.Source.from_file(dot_file)
                s.render(pdf_file, format='pdf', view=False, cleanup=False)
                pdf_file += ".pdf"
            if options.export_svg:
                svg_file = gremlin.util.next_file(file_base + ".svg", False)
                s = graphviz.Source.from_file(dot_file)
                s.render(svg_file, format='svg', view=False, cleanup=False)
                svg_file += ".svg"

            if options.show_folder:
                # open the file in the folder
                if options.export_pdf and os.path.isfile(pdf_file):
                    gremlin.util.open_folder(pdf_file)
                elif options.export_svg and os.path.isfile(svg_file):
                    gremlin.util.open_folder(svg_file)

            if options.open_files:
                if options.export_pdf and os.path.isfile(pdf_file):
                    gremlin.util.display_file(pdf_file)
                if options.export_svg and os.path.isfile(svg_file):
                    gremlin.util.display_file(svg_file)

            os.unlink(dot_file) # clean up
        except Exception as err:
            # if os.path.isfile(dot_file):
            #     gremlin.util.display_file(dot_file)
            syslog.error(f"REPORT: error rendering: {err}\n{traceback.format_exc()}")

