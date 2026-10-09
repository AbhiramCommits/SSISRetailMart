"""A small SSIS-expression evaluator.

Supports the subset of the SSIS expression language used by the packages in
``ssis/packages``:

* column references ``[Col]`` and variables ``@[User::Var]``
* string / numeric / NULL literals, ``TRUE`` / ``FALSE``
* arithmetic ``+ - * / %`` and string concatenation with ``+``
* comparisons ``= == <> != < <= > >=``, logical ``&& || AND OR NOT``
* the ternary ``cond ? a : b`` (short-circuiting)
* casts ``(DT_I4)``, ``(DT_I8)``, ``(DT_STR,n)``, ``(DT_DECIMAL,s)``,
  ``(DT_R8)``, ``(DT_DATE)``, ``(DT_DBDATE)``, ``(DT_BOOL)``
* functions TRIM, LTRIM, RTRIM, UPPER, LOWER, LEN, SUBSTRING, LEFT, RIGHT,
  REPLACE, ISNULL, CONCAT, YEAR, MONTH, DAY, GETDATE and the custom
  ROW_HASH (SHA-256 over the concatenated arguments).
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

__all__ = ["evaluate", "ExpressionError", "CastError", "compile_expression"]


class ExpressionError(Exception):
    """Raised when an expression cannot be parsed."""


class CastError(ExpressionError):
    """Raised when a runtime cast fails (drives error-output redirection)."""


_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<string>"(?:[^"]|"")*")
      | (?P<var>@\[[^\]]+\])
      | (?P<col>\[[^\]]+\])
      | (?P<cast>\(DT_[A-Z0-9_]+(?:\s*,\s*\d+)?\))
      | (?P<number>\d+\.\d+|\d+)
      | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<op><>|<=|>=|!=|==|&&|\|\||[-+*/%(),?:=<>])
    )
    """,
    re.VERBOSE,
)

_CAST_TYPES = {
    "DT_STR",
    "DT_WSTR",
    "DT_I1",
    "DT_I2",
    "DT_I4",
    "DT_I8",
    "DT_U1",
    "DT_U2",
    "DT_U4",
    "DT_U8",
    "DT_R4",
    "DT_R8",
    "DT_DECIMAL",
    "DT_NUMERIC",
    "DT_DATE",
    "DT_DBDATE",
    "DT_DBTIMESTAMP",
    "DT_BOOL",
    "DT_DATE_KEY",
}


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    length = len(text)
    while pos < length:
        match = _TOKEN_RE.match(text, pos)
        if not match:
            raise ExpressionError(f"cannot tokenize {text[pos:pos + 20]!r}")
        pos = match.end()
        kind = match.lastgroup
        value = match.group(kind)
        tokens.append((kind, value))
    tokens.append(("eof", ""))
    return tokens


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = _tokenize(text)
        self.index = 0

    def peek(self) -> tuple[str, str]:
        return self.tokens[self.index]

    def next(self) -> tuple[str, str]:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def expect_op(self, value: str) -> None:
        kind, token = self.next()
        if (kind, token.upper() if kind == "name" else token) != ("op", value):
            raise ExpressionError(f"expected {value!r} in {self.text!r}, got {token!r}")

    # recursive descent -------------------------------------------------
    def parse(self):
        node = self.parse_ternary()
        if self.peek()[0] != "eof":
            raise ExpressionError(f"unexpected trailing input in {self.text!r}")
        return node

    def parse_ternary(self):
        cond = self.parse_or()
        kind, token = self.peek()
        if kind == "op" and token == "?":
            self.next()
            yes = self.parse_ternary()
            self.expect_op(":")
            no = self.parse_ternary()
            return ("ternary", cond, yes, no)
        return cond

    def parse_or(self):
        node = self.parse_and()
        while True:
            kind, token = self.peek()
            if kind == "op" and token == "||":
                self.next()
                node = ("or", node, self.parse_and())
            elif kind == "name" and token.upper() == "OR":
                self.next()
                node = ("or", node, self.parse_and())
            else:
                return node

    def parse_and(self):
        node = self.parse_not()
        while True:
            kind, token = self.peek()
            if kind == "op" and token == "&&":
                self.next()
                node = ("and", node, self.parse_not())
            elif kind == "name" and token.upper() == "AND":
                self.next()
                node = ("and", node, self.parse_not())
            else:
                return node

    def parse_not(self):
        kind, token = self.peek()
        if (kind == "name" and token.upper() == "NOT") or (
            kind == "op" and token == "!"
        ):
            self.next()
            return ("not", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        node = self.parse_additive()
        kind, token = self.peek()
        if kind == "op" and token in ("=", "==", "<>", "!=", "<", "<=", ">", ">="):
            self.next()
            return ("cmp", token, node, self.parse_additive())
        return node

    def parse_additive(self):
        node = self.parse_multiplicative()
        while True:
            kind, token = self.peek()
            if kind == "op" and token in ("+", "-"):
                self.next()
                node = ("bin", token, node, self.parse_multiplicative())
            else:
                return node

    def parse_multiplicative(self):
        node = self.parse_unary()
        while True:
            kind, token = self.peek()
            if kind == "op" and token in ("*", "/", "%"):
                self.next()
                node = ("bin", token, node, self.parse_unary())
            else:
                return node

    def parse_unary(self):
        kind, token = self.peek()
        if kind == "op" and token in ("-", "+"):
            self.next()
            return ("un", token, self.parse_unary())
        if kind == "cast":
            self.next()
            return ("cast", token, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        kind, token = self.next()
        if kind == "number":
            return ("num", Decimal(token) if "." in token else int(token))
        if kind == "string":
            return ("str", token[1:-1].replace('""', '"'))
        if kind == "col":
            return ("col", token[1:-1])
        if kind == "var":
            return ("var", token[2:-1])
        if kind == "op" and token == "(":
            node = self.parse_ternary()
            self.expect_op(")")
            return node
        if kind == "op" and token == "-":
            return ("un", "-", self.parse_unary())
        if kind == "name":
            upper = token.upper()
            if upper == "NULL":
                return ("null",)
            if upper == "TRUE":
                return ("bool", True)
            if upper == "FALSE":
                return ("bool", False)
            nxt_kind, nxt = self.peek()
            if nxt_kind == "op" and nxt == "(":
                self.next()
                args = []
                if not (self.peek() == ("op", ")")):
                    args.append(self.parse_ternary())
                    while self.peek() == ("op", ","):
                        self.next()
                        args.append(self.parse_ternary())
                self.expect_op(")")
                return ("func", upper, args)
            return ("name", token)
        raise ExpressionError(f"unexpected token {token!r} in {self.text!r}")


def compile_expression(text: str):
    """Parse ``text`` once and return an ``eval(row, variables)`` callable."""
    node = _Parser(text).parse()

    def evaluate_callable(row: dict, variables: dict):
        return _eval(node, row, variables)

    return evaluate_callable


def evaluate(text: str, row: dict, variables: dict):
    return _eval(_Parser(text).parse(), row, variables)


# evaluation --------------------------------------------------------------
def _is_null(value) -> bool:
    return value is None


def _num(value):
    if isinstance(value, bool):
        return int(value)
    return value


def _to_decimal(value, scale=None):
    if value is None:
        return None
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CastError(f"cannot convert {value!r} to decimal") from exc
    if scale is not None:
        quant = Decimal(1).scaleb(-scale)
        dec = dec.quantize(quant, rounding=ROUND_HALF_UP)
    return dec


def _to_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise CastError(f"cannot convert {value!r} to integer") from exc


def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise CastError(f"cannot convert {value!r} to date")


def _apply_cast(type_name: str, scale, value):
    if type_name in ("DT_STR", "DT_WSTR"):
        return None if value is None else str(value)
    if type_name in ("DT_I1", "DT_I2", "DT_I4", "DT_I8", "DT_U1", "DT_U2", "DT_U4", "DT_U8"):
        return _to_int(value)
    if type_name in ("DT_R4", "DT_R8"):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise CastError(f"cannot convert {value!r} to float") from exc
    if type_name in ("DT_DECIMAL", "DT_NUMERIC"):
        return _to_decimal(value, scale)
    if type_name in ("DT_DATE", "DT_DBDATE", "DT_DBTIMESTAMP"):
        return _to_date(value)
    if type_name == "DT_BOOL":
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float, Decimal)):
            return value != 0
        return str(value).strip().lower() in ("1", "true", "yes", "y", "t")
    if type_name == "DT_DATE_KEY":
        d = _to_date(value)
        return None if d is None else d.year * 10000 + d.month * 100 + d.day
    raise CastError(f"unsupported cast type {type_name}")


def _truthy(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    return str(value) != ""


def _eval(node, row, variables):
    tag = node[0]
    if tag == "num" or tag == "str" or tag == "bool":
        return node[1]
    if tag == "null":
        return None
    if tag == "col":
        return row.get(node[1])
    if tag == "var":
        name = node[1]
        key = name.split("::", 1)[1] if "::" in name else name
        return variables.get(key)
    if tag == "name":
        return variables.get(node[1])
    if tag == "un":
        op, operand = node[1], _eval(node[2], row, variables)
        if operand is None:
            return None
        if op == "-":
            return -operand
        return +operand
    if tag == "not":
        return not _truthy(_eval(node[1], row, variables))
    if tag == "and":
        left = _eval(node[1], row, variables)
        if not _truthy(left):
            return False
        return _truthy(_eval(node[2], row, variables))
    if tag == "or":
        left = _eval(node[1], row, variables)
        if _truthy(left):
            return True
        return _truthy(_eval(node[2], row, variables))
    if tag == "cmp":
        op, left, right = node[1], _eval(node[2], row, variables), _eval(node[3], row, variables)
        if left is None or right is None:
            return None
        if op in ("=", "=="):
            return left == right
        if op in ("<>", "!="):
            return left != right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
    if tag == "ternary":
        if _truthy(_eval(node[1], row, variables)):
            return _eval(node[2], row, variables)
        return _eval(node[3], row, variables)
    if tag == "bin":
        return _eval_binary(node[1], _eval(node[2], row, variables), _eval(node[3], row, variables))
    if tag == "cast":
        type_token = node[1]
        inner = type_token[1:-1]
        parts = [p.strip() for p in inner.split(",")]
        type_name = parts[0]
        scale = int(parts[1]) if len(parts) > 1 else None
        return _apply_cast(type_name, scale, _eval(node[2], row, variables))
    if tag == "func":
        return _eval_func(node[1], [_eval(arg, row, variables) for arg in node[2]])
    raise ExpressionError(f"unknown node {tag!r}")


def _eval_binary(op, left, right):
    if op == "+":
        if isinstance(left, str) or isinstance(right, str):
            if left is None or right is None:
                return None
            return str(left) + str(right)
        if left is None or right is None:
            return None
        return left + right
    if left is None or right is None:
        return None
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise ExpressionError("division by zero")
        return left / right
    if op == "%":
        return left % right
    raise ExpressionError(f"unknown operator {op!r}")


def _eval_func(name, args):
    if name == "TRIM":
        return None if args[0] is None else str(args[0]).strip()
    if name == "LTRIM":
        return None if args[0] is None else str(args[0]).lstrip()
    if name == "RTRIM":
        return None if args[0] is None else str(args[0]).rstrip()
    if name == "UPPER":
        return None if args[0] is None else str(args[0]).upper()
    if name == "LOWER":
        return None if args[0] is None else str(args[0]).lower()
    if name == "LEN":
        return 0 if args[0] is None else len(str(args[0]).strip())
    if name == "ISNULL":
        return args[0] is None
    if name == "CONCAT":
        return "".join("" if a is None else str(a) for a in args)
    if name == "SUBSTRING":
        value, start, length = args[0], _to_int(args[1]), _to_int(args[2])
        if value is None:
            return None
        return str(value)[start - 1 : start - 1 + length]
    if name in ("LEFT", "RIGHT"):
        value, length = args[0], _to_int(args[1])
        if value is None:
            return None
        text = str(value)
        return text[:length] if name == "LEFT" else text[-length:] if length else ""
    if name == "REPLACE":
        if any(a is None for a in args):
            return None
        return str(args[0]).replace(str(args[1]), str(args[2]))
    if name == "YEAR":
        d = _to_date(args[0])
        return None if d is None else d.year
    if name == "MONTH":
        d = _to_date(args[0])
        return None if d is None else d.month
    if name == "DAY":
        d = _to_date(args[0])
        return None if d is None else d.day
    if name == "GETDATE":
        return datetime.now()
    if name in ("ROW_HASH", "HASH"):
        payload = "|".join("" if a is None else str(a) for a in args)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    raise ExpressionError(f"unknown function {name}")
