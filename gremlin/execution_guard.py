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


"""
This module provides a way for an execution path to cancel execution and
cooperatively cancel further execution if needed. It allows
for the propagation of an abort signal through nested calls while
maintaining context about the current event, node, and action.

Decorators provided by this module are used to wrap functions and
automatically handle execution aborts, ensuring that the abort signal
is propagated correctly and that appropriate cleanup or logging occurs.

"""

from functools import wraps
import logging
import threading


syslog = logging.getLogger("system")
_context = threading.local()


class ExecutionAborted(Exception):
    """Control flow used to unwind execution, independently of condition results."""


class _Execution:
    __slots__ = ("abort", "event", "node_id", "action_id", "steps")

    def __init__(self):
        self.abort = None
        self.event = None
        self.node_id = None
        self.action_id = None
        self.steps = 0


def checkpoint(event=None, node=None, functor=None):
    """Reject further work even if a callback swallowed the original abort."""
    execution = getattr(_context, "execution", None)
    if execution is None:
        return
    if execution.abort is not None:
        raise execution.abort
    if event is not None and execution.event is None:
        execution.event = event
    if node is not None:
        execution.node_id = node.id
    if functor is not None:
        execution.action_id = getattr(functor, "id", None)
        execution.steps += 1


def abort(reason):
    """Latch cancellation before raising; the first reason wins."""
    execution = getattr(_context, "execution", None)
    if execution is None:
        raise ExecutionAborted(reason)
    if execution.abort is None:
        execution.abort = ExecutionAborted(reason)
    raise execution.abort


def _decorate(method, catch_abort, aborted_result=None):
    @wraps(method)
    def guarded_call(*args, **kwargs):
        execution = getattr(_context, "execution", None)
        owner = execution is None
        if owner:
            execution = _Execution()
            _context.execution = execution
        try:
            checkpoint()
            result = method(*args, **kwargs)
            checkpoint()
            return result
        except Exception as error:
            # psygnal wraps callback exceptions. The cancellation flag survives
            # both that wrapping and plugins catching Exception themselves.
            if execution.abort is None and isinstance(error, ExecutionAborted):
                execution.abort = error
            if execution.abort is None:
                raise
            if owner:
                event = execution.event
                syslog.warning(
                    "EXECUTION ABORTED: %s (mode=%s input=%s node=%s action=%s steps=%s)",
                    execution.abort,
                    getattr(event, "mode", None),
                    getattr(event, "identifier", None),
                    execution.node_id,
                    execution.action_id,
                    execution.steps,
                )
                if catch_abort:
                    return aborted_result
            if error is execution.abort:
                raise
            raise execution.abort from None
        finally:
            if owner:
                # Exception tracebacks retain execution frames. Production can
                # disable cyclic GC, so detach the control-flow exception too.
                if execution.abort is not None:
                    execution.abort.__traceback__ = None
                    execution.abort.__context__ = None
                    execution.abort.__cause__ = None
                execution.abort = None
                execution.event = None
                del _context.execution

    return guarded_call


def boundary(method=None, *, aborted_result=None):
    """Handle cancellation only when this dispatcher owns the entire chain."""
    if method is None:
        return lambda method: _decorate(method, catch_abort=True, aborted_result=aborted_result)
    return _decorate(method, catch_abort=True, aborted_result=aborted_result)


def guarded(method):
    """Establish a scope for direct engine calls, propagating cancellation."""
    return _decorate(method, catch_abort=False)
