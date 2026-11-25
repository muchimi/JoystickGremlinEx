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


"""Wire-compatible subset of the Star Citizen telemetry service.

uses the Google protobuf library for message serialization and deserialization.

"""

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

SERVICE = "/sc.game.telemetry.v1.GameTelemetryService/"

# Only fields used by Gremlin are described here. Unknown fields are skipped by
# protobuf. The numeric layout is documented by the sc-telemetry-deck project.
# https://github.com/Sokren/sc-telemetry-deck/blob/main/schema/sc_extrait.proto
_MESSAGES = {
    "FlightState": ((1, "landed", "bool"), (2, "gear", "uint32"), (3, "vtol", "uint32"), (4, "transformation", "uint32")),
    "Flight": ((1, "state", "FlightState"),),
    "Power": (
        (1, "main", "bool"),
        (2, "engines", "bool"),
        (3, "weapons", "bool"),
        (4, "coolers", "bool"),
        (5, "life_support", "bool"),
        (6, "gravity_generators", "bool"),
        (7, "sensors", "bool"),
        (8, "shield_generators", "bool"),
        (9, "shield_emitters", "bool"),
    ),
    "Annunciators": ((4, "shields", "uint32"), (6, "quantum_drive", "uint32")),
    "MasterMode": ((1, "mode", "uint32"), (2, "spooled", "bool")),
    "VehicleState": (
        (1, "name", "string"),
        (2, "class_name", "string"),
        (5, "lights", "bool"),
        (7, "annunciators", "Annunciators"),
        (8, "flight", "Flight"),
        (9, "power", "Power"),
        (12, "master_mode", "MasterMode"),
    ),
    "VehicleFrame": ((2, "state", "VehicleState"),),
    "TelemetryFrame": ((3, "vehicle", "VehicleFrame"),),
    "ActionRequest": ((1, "action_name", "string"), (2, "hold_ms", "uint32")),
    "ActionResponse": ((1, "status", "uint32"), (2, "message", "string")),
    "TriggerableAction": ((1, "action_name", "string"), (3, "holdable", "bool")),
    "ActionList": ((1, "actions", "TriggerableAction", True),),
}


def _message_classes():
    field_type = descriptor_pb2.FieldDescriptorProto
    scalar_types = {
        "bool": field_type.TYPE_BOOL,
        "uint32": field_type.TYPE_UINT32,
        "string": field_type.TYPE_STRING,
    }
    schema = descriptor_pb2.FileDescriptorProto(name="gex_star_citizen.proto", package="gex.star_citizen", syntax="proto2")
    for name, fields in _MESSAGES.items():
        message = schema.message_type.add(name=name)
        for number, field_name, kind, *repeated in fields:
            field = message.field.add(
                name=field_name,
                number=number,
                type=scalar_types.get(kind, field_type.TYPE_MESSAGE),
                label=field_type.LABEL_REPEATED if repeated else field_type.LABEL_OPTIONAL,
            )
            if kind not in scalar_types:
                field.type_name = f".{schema.package}.{kind}"
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    return {name: message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{schema.package}.{name}")) for name in _MESSAGES}


_TYPES = _message_classes()
TelemetryFrame = _TYPES["TelemetryFrame"]
ActionList = _TYPES["ActionList"]
ActionRequest = _TYPES["ActionRequest"]
ActionResponse = _TYPES["ActionResponse"]
