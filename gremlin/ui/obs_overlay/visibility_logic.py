# -*- coding: utf-8; -*-
#
# Overlay visibility boolean expressions (A AND (B OR C), XOR, …).
#
# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026

from __future__ import annotations

from typing import Any, Callable

LETTERS = tuple(chr(ord("A") + i) for i in range(26))

_OP_WORDS = {
    "AND": "AND",
    "OR": "OR",
    "XOR": "XOR",
    "NAND": "NAND",
    "NOR": "NOR",
    "XNOR": "XNOR",
    "NOT": "NOT",
    "NXOR": "XNOR",
}

# precedence, associativity, arity
_OPS = {
    "NOT": (4, "right", 1),
    "AND": (3, "left", 2),
    "NAND": (3, "left", 2),
    "XOR": (2, "left", 2),
    "XNOR": (2, "left", 2),
    "OR": (1, "left", 2),
    "NOR": (1, "left", 2),
}

_SYMBOL_OP = {
    "·": "AND",
    "⋅": "AND",
    "*": "AND",
    "&": "AND",
    "∧": "AND",
    "+": "OR",
    "|": "OR",
    "∨": "OR",
    "^": "XOR",
    "⊕": "XOR",
    "⊻": "XOR",
    "¬": "NOT",
    "~": "NOT",
    "!": "NOT",
}

_PRETTY = {
    "AND": "·",
    "OR": "+",
    "XOR": "⊕",
    "NAND": "NAND",
    "NOR": "NOR",
    "XNOR": "⊙",
    "NOT": "¬",
}


class VisibilityExprError(ValueError):
    pass


def next_condition_letter(used) -> str:
    taken = {str(letter or "").strip().upper() for letter in (used or [])}
    for letter in LETTERS:
        if letter not in taken:
            return letter
    return ""


def normalize_letter(value) -> str:
    letter = str(value or "").strip().upper()
    if len(letter) == 1 and "A" <= letter <= "Z":
        return letter
    return ""


def assign_condition_letters(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    used: set[str] = set()
    pending = []
    for cond in conditions:
        letter = normalize_letter(cond.get("letter"))
        if letter and letter not in used:
            cond["letter"] = letter
            used.add(letter)
        else:
            cond["letter"] = ""
            pending.append(cond)
    for cond in pending:
        letter = next_condition_letter(used)
        cond["letter"] = letter
        if letter:
            used.add(letter)
    return conditions


def default_join_expression(letters: list[str], join: str = "all") -> str:
    names = [str(letter).strip().upper() for letter in letters if str(letter or "").strip()]
    if not names:
        return ""
    op = " OR " if str(join or "all").casefold() == "any" else " AND "
    return op.join(names)


def effective_visibility_expression(vis: dict[str, Any] | None, letters: list[str] | None = None) -> str:
    vis = vis or {}
    text = str(vis.get("expression") or "").strip()
    if text:
        return text
    if letters is None:
        letters = [str(c.get("letter") or "") for c in (vis.get("conditions") or []) if isinstance(c, dict)]
    return default_join_expression(letters, str(vis.get("join") or "all"))


class _Lit:
    __slots__ = ("letter",)

    def __init__(self, letter: str):
        self.letter = letter


class _Unary:
    __slots__ = ("op", "a")

    def __init__(self, op: str, a):
        self.op = op
        self.a = a


class _Binary:
    __slots__ = ("op", "a", "b")

    def __init__(self, op: str, a, b):
        self.op = op
        self.a = a
        self.b = b


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "()":
            tokens.append(("paren", ch))
            i += 1
            continue
        if ch in _SYMBOL_OP:
            tokens.append(("op", _SYMBOL_OP[ch]))
            i += 1
            continue
        if ch.isalpha():
            j = i + 1
            while j < n and text[j].isalpha():
                j += 1
            word = text[i:j].upper()
            if word in _OP_WORDS:
                tokens.append(("op", _OP_WORDS[word]))
            elif len(word) == 1:
                tokens.append(("letter", word))
            else:
                raise VisibilityExprError(f"Unknown name “{text[i:j]}”. Use A–Z or AND, OR, XOR, NAND, NOR, XNOR, NOT.")
            i = j
            continue
        raise VisibilityExprError(f"Unexpected “{ch}” in the expression.")
    return tokens


def parse_visibility_expression(text: str):
    """Return an AST, or None when *text* is empty."""
    source = str(text or "").strip()
    if not source:
        return None
    tokens = _tokenize(source)
    output: list = []
    ops: list[str] = []

    def _prec(op: str) -> int:
        return _OPS[op][0]

    def _right(op: str) -> bool:
        return _OPS[op][1] == "right"

    def _reduce(op: str):
        try:
            if _OPS[op][2] == 1:
                if not output:
                    raise VisibilityExprError("NOT is missing a value.")
                output.append(_Unary(op, output.pop()))
                return
            if len(output) < 2:
                raise VisibilityExprError(f"{op} needs two values.")
            b = output.pop()
            a = output.pop()
            output.append(_Binary(op, a, b))
        except IndexError as err:
            raise VisibilityExprError("The expression is incomplete.") from err

    prev = None
    for kind, value in tokens:
        if kind == "letter":
            if prev in ("letter", "paren_close"):
                raise VisibilityExprError("Put AND / OR / XOR between letters, or use parentheses.")
            output.append(_Lit(value))
            prev = "letter"
            continue
        if kind == "paren" and value == "(":
            if prev in ("letter", "paren_close"):
                raise VisibilityExprError("Put an operator before “(”.")
            ops.append("(")
            prev = "paren_open"
            continue
        if kind == "paren" and value == ")":
            while ops and ops[-1] != "(":
                _reduce(ops.pop())
            if not ops:
                raise VisibilityExprError("Unmatched “)”.")
            ops.pop()
            prev = "paren_close"
            continue
        op = value
        if op == "NOT" and prev in ("letter", "paren_close"):
            raise VisibilityExprError("NOT goes before a letter, not after.")
        while ops and ops[-1] != "(":
            top = ops[-1]
            if _right(op):
                if _prec(op) < _prec(top):
                    _reduce(ops.pop())
                    continue
            elif _prec(op) <= _prec(top):
                _reduce(ops.pop())
                continue
            break
        ops.append(op)
        prev = "op"
    while ops:
        op = ops.pop()
        if op == "(":
            raise VisibilityExprError("Unmatched “(”.")
        _reduce(op)
    if len(output) != 1:
        raise VisibilityExprError("The expression is incomplete.")
    return output[0]


def expression_letters(node) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def walk(item):
        if item is None:
            return
        if isinstance(item, _Lit):
            if item.letter not in seen:
                seen.add(item.letter)
                found.append(item.letter)
            return
        if isinstance(item, _Unary):
            walk(item.a)
            return
        if isinstance(item, _Binary):
            walk(item.a)
            walk(item.b)

    walk(node)
    return found


def eval_visibility_node(node, env: dict[str, bool]) -> bool:
    if node is None:
        return True
    if isinstance(node, _Lit):
        return bool(env.get(node.letter, False))
    if isinstance(node, _Unary):
        value = eval_visibility_node(node.a, env)
        return not value
    a = eval_visibility_node(node.a, env)
    b = eval_visibility_node(node.b, env)
    op = node.op
    if op == "AND":
        return a and b
    if op == "OR":
        return a or b
    if op == "XOR":
        return a != b
    if op == "NAND":
        return not (a and b)
    if op == "NOR":
        return not (a or b)
    if op == "XNOR":
        return a == b
    raise VisibilityExprError(f"Unknown operator {op}.")


def pretty_visibility_expression(node) -> str:
    if node is None:
        return ""
    if isinstance(node, _Lit):
        return node.letter
    if isinstance(node, _Unary):
        inner = pretty_visibility_expression(node.a)
        if isinstance(node.a, _Lit):
            return f"{inner}\u0305"
        return f"¬({inner})"
    left = pretty_visibility_expression(node.a)
    right = pretty_visibility_expression(node.b)
    if isinstance(node.a, _Binary) and _OPS[node.a.op][0] < _OPS[node.op][0]:
        left = f"({left})"
    if isinstance(node.b, (_Binary, _Unary)) and (
        isinstance(node.b, _Unary) or _OPS[node.b.op][0] <= _OPS[node.op][0]
    ):
        right = f"({right})"
    symbol = _PRETTY.get(node.op, node.op)
    if node.op == "NAND":
        return f"¬({left} · {right})"
    if node.op == "NOR":
        return f"¬({left} + {right})"
    if node.op == "XNOR":
        return f"¬({left} ⊕ {right})"
    return f"{left} {symbol} {right}"


def truth_table(node, letters: list[str]) -> list[tuple[dict[str, bool], bool]]:
    names = [str(letter).upper() for letter in letters if str(letter or "").strip()]
    rows = []
    count = 1 << len(names)
    for index in range(count):
        env = {}
        # High bit is the first letter so A changes slowest (matches typical textbooks).
        for bit, letter in enumerate(names):
            env[letter] = bool(index & (1 << (len(names) - 1 - bit)))
        rows.append((env, eval_visibility_node(node, env) if node is not None else True))
    return rows


def evaluate_visibility_expression(text: str, env: dict[str, bool]) -> bool:
    node = parse_visibility_expression(text)
    if node is None:
        return True
    missing = [letter for letter in expression_letters(node) if letter not in env]
    if missing:
        raise VisibilityExprError(f"Unknown letter {', '.join(missing)}. Add that condition first.")
    return eval_visibility_node(node, env)


def compile_visibility_expression(text: str) -> Callable[[dict[str, bool]], bool] | None:
    node = parse_visibility_expression(text)
    if node is None:
        return None

    def _eval(env: dict[str, bool], tree=node) -> bool:
        return eval_visibility_node(tree, env)

    return _eval
