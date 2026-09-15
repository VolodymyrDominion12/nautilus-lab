"""Constrained factor DSL: parse, evaluate, complexity, crowding.

Formulas are *recipes*, not Python. The evaluator uses only closed-bar feature
rows (point-in-time). Cross-sectional operators (`rank`, `corr`) are rejected:
this lab scores one instrument at a time.

See LLM-crypto research § From Hypotheses to Factors / QuantaAlpha.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.errors import InvalidHypothesisError
from nautilus_lab.domain.formulaic_alphas import FEATURE_NAMES

MAX_DEPTH = 6
MAX_COMPLEXITY = Decimal("32")
MAX_CROWDING_SIMILARITY = Decimal("0.85")
CROSS_SECTIONAL = frozenset({"rank", "corr"})

_UNARY_FUNCS = frozenset({"abs", "log", "sign", "sqrt"})
_WINDOW_FUNCS = frozenset({"ts_mean", "ts_std", "ts_max", "ts_min", "delay", "delta"})
_OPTIONAL_WINDOW = frozenset({"mean", "std", "sum", "zscore"})
_COMMUTATIVE = frozenset({"+", "*"})


@dataclass(frozen=True, slots=True)
class Literal:
    value: Decimal


@dataclass(frozen=True, slots=True)
class Feature:
    name: str


@dataclass(frozen=True, slots=True)
class UnaryOp:
    op: str
    arg: FactorNode


@dataclass(frozen=True, slots=True)
class BinaryOp:
    op: str
    left: FactorNode
    right: FactorNode


@dataclass(frozen=True, slots=True)
class CallOp:
    name: str
    args: tuple[FactorNode, ...]


type FactorNode = Literal | Feature | UnaryOp | BinaryOp | CallOp


def parse_recipe(formula: str) -> FactorNode:
    """Parse a formula into an AST. Fail closed on unknown tokens or functions."""
    parser = _Parser(formula)
    node = parser.parse()
    _validate_recipe(node)
    return node


def recipe_complexity(node: FactorNode) -> Decimal:
    """QuantaAlpha-style: length + free parameters + unique raw features."""
    return Decimal(node_count(node) + free_param_count(node) + len(unique_features(node)))


def node_count(node: FactorNode) -> int:
    return 1 + sum(node_count(child) for child in _children(node))


def recipe_depth(node: FactorNode) -> int:
    kids = _children(node)
    if not kids:
        return 0
    return 1 + max(recipe_depth(child) for child in kids)


def unique_features(node: FactorNode) -> frozenset[str]:
    if isinstance(node, Feature):
        return frozenset({node.name})
    names: set[str] = set()
    for child in _children(node):
        names |= unique_features(child)
    return frozenset(names)


def free_param_count(node: FactorNode) -> int:
    """Numeric literals that are windows or thresholds, not arithmetic constants."""
    if isinstance(node, CallOp):
        return sum(1 for arg in node.args if isinstance(arg, Literal)) + sum(
            free_param_count(arg) for arg in node.args if not isinstance(arg, Literal)
        )
    return sum(free_param_count(child) for child in _children(node))


def ast_similarity(left: FactorNode, right: FactorNode) -> Decimal:
    """Largest common isomorphic subtree over max size. Literals match structurally."""
    largest = _largest_common(left, right)
    denom = max(node_count(left), node_count(right))
    if denom == 0:
        return Decimal("0")
    return Decimal(largest) / Decimal(denom)


def crowding_hits(
    candidate: FactorNode,
    pool: Sequence[FactorNode],
    *,
    max_similarity: Decimal = MAX_CROWDING_SIMILARITY,
) -> tuple[int, ...]:
    """Indices of pool recipes that are near-duplicates of `candidate`."""
    if max_similarity < 0 or max_similarity > 1:
        raise ValueError("max_similarity must be in [0, 1]")
    return tuple(
        index
        for index, other in enumerate(pool)
        if ast_similarity(candidate, other) > max_similarity
    )


def evaluate_recipe(
    node: FactorNode,
    rows: Sequence[Mapping[str, Decimal]],
    *,
    index: int,
) -> Decimal | None:
    """Value of `node` at `index` using only rows `<= index`. None = not ready."""
    if index < 0 or index >= len(rows):
        return None
    return _eval(node, rows, index)


def _validate_recipe(node: FactorNode) -> None:
    depth = recipe_depth(node)
    if depth > MAX_DEPTH:
        raise InvalidHypothesisError(f"recipe depth {depth} exceeds max {MAX_DEPTH}")
    complexity = recipe_complexity(node)
    if complexity > MAX_COMPLEXITY:
        raise InvalidHypothesisError(f"recipe complexity {complexity} exceeds max {MAX_COMPLEXITY}")
    if _is_too_shallow(node):
        raise InvalidHypothesisError(
            "recipe must combine or transform features, not a single raw column"
        )


def _is_too_shallow(node: FactorNode) -> bool:
    if isinstance(node, (Literal, Feature)):
        return True
    if isinstance(node, UnaryOp) and node.op == "neg":
        return _is_too_shallow(node.arg)
    return False


def _children(node: FactorNode) -> tuple[FactorNode, ...]:
    if isinstance(node, UnaryOp):
        return (node.arg,)
    if isinstance(node, BinaryOp):
        return (node.left, node.right)
    if isinstance(node, CallOp):
        return node.args
    return ()


def _subtrees(node: FactorNode) -> list[FactorNode]:
    found = [node]
    for child in _children(node):
        found.extend(_subtrees(child))
    return found


def _largest_common(left: FactorNode, right: FactorNode) -> int:
    best = _match_from_roots(left, right)
    for a_node in _subtrees(left):
        for b_node in _subtrees(right):
            best = max(best, _match_from_roots(a_node, b_node))
    return best


def _match_from_roots(left: FactorNode, right: FactorNode) -> int:
    if type(left) is not type(right):
        return 0
    if isinstance(left, Literal) and isinstance(right, Literal):
        return 1
    if isinstance(left, Feature) and isinstance(right, Feature):
        return 1 if left.name == right.name else 0
    if isinstance(left, UnaryOp) and isinstance(right, UnaryOp):
        if left.op != right.op:
            return 0
        return 1 + _match_from_roots(left.arg, right.arg)
    if isinstance(left, BinaryOp) and isinstance(right, BinaryOp):
        if left.op != right.op:
            return 0
        direct = _match_from_roots(left.left, right.left) + _match_from_roots(
            left.right, right.right
        )
        if left.op in _COMMUTATIVE:
            swapped = _match_from_roots(left.left, right.right) + _match_from_roots(
                left.right, right.left
            )
            return 1 + max(direct, swapped)
        return 1 + direct
    if isinstance(left, CallOp) and isinstance(right, CallOp):
        if left.name != right.name or len(left.args) != len(right.args):
            return 0
        return 1 + sum(
            _match_from_roots(a_arg, b_arg)
            for a_arg, b_arg in zip(left.args, right.args, strict=True)
        )
    return 0


def _eval(
    node: FactorNode,
    rows: Sequence[Mapping[str, Decimal]],
    index: int,
) -> Decimal | None:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Feature):
        row = rows[index]
        return row.get(node.name)
    if isinstance(node, UnaryOp):
        value = _eval(node.arg, rows, index)
        if value is None:
            return None
        return _apply_unary(node.op, value)
    if isinstance(node, BinaryOp):
        left = _eval(node.left, rows, index)
        right = _eval(node.right, rows, index)
        if left is None or right is None:
            return None
        return _apply_binary(node.op, left, right)
    return _eval_call(node, rows, index)


def _apply_unary(op: str, value: Decimal) -> Decimal | None:
    if op == "neg":
        return -value
    if op == "abs":
        return abs(value)
    if op == "sign":
        if value > 0:
            return Decimal("1")
        if value < 0:
            return Decimal("-1")
        return Decimal("0")
    if op == "log":
        if value <= 0:
            return None
        return value.ln()
    if op == "sqrt":
        if value < 0:
            return None
        return value.sqrt()
    raise InvalidHypothesisError(f"unknown unary operator {op!r}")


def _apply_binary(op: str, left: Decimal, right: Decimal) -> Decimal | None:
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            return None
        return left / right
    if op == "**":
        if left < 0 and right != right.to_integral_value():
            return None
        return left**right
    raise InvalidHypothesisError(f"unknown binary operator {op!r}")


def _eval_call(
    node: CallOp,
    rows: Sequence[Mapping[str, Decimal]],
    index: int,
) -> Decimal | None:
    name = node.name
    if name in _UNARY_FUNCS:
        if len(node.args) != 1:
            return None
        value = _eval(node.args[0], rows, index)
        if value is None:
            return None
        return _apply_unary(name, value)
    if name == "clip":
        if len(node.args) != 3:
            return None
        value = _eval(node.args[0], rows, index)
        lo = _eval(node.args[1], rows, index)
        hi = _eval(node.args[2], rows, index)
        if value is None or lo is None or hi is None:
            return None
        if lo > hi:
            lo, hi = hi, lo
        return min(max(value, lo), hi)
    if name in {"max", "min"}:
        if len(node.args) != 2:
            return None
        left = _eval(node.args[0], rows, index)
        right = _eval(node.args[1], rows, index)
        if left is None or right is None:
            return None
        return max(left, right) if name == "max" else min(left, right)
    if name == "pow":
        if len(node.args) != 2:
            return None
        base = _eval(node.args[0], rows, index)
        exp = _eval(node.args[1], rows, index)
        if base is None or exp is None:
            return None
        return _apply_binary("**", base, exp)
    if name in _WINDOW_FUNCS or name in _OPTIONAL_WINDOW:
        return _eval_windowed(node, rows, index)
    raise InvalidHypothesisError(f"unknown function {name!r}")


def _eval_windowed(
    node: CallOp,
    rows: Sequence[Mapping[str, Decimal]],
    index: int,
) -> Decimal | None:
    expr = node.args[0]
    window = _window_size(node, index=index)
    if window is None:
        return None
    if node.name == "delay":
        target = index - window
        if target < 0:
            return None
        return _eval(expr, rows, target)
    if node.name == "delta":
        current = _eval(expr, rows, index)
        lagged = _eval(expr, rows, index - window) if index - window >= 0 else None
        if current is None or lagged is None:
            return None
        return current - lagged
    start = index - window + 1
    if start < 0:
        return None
    explicit_window = len(node.args) == 2
    values: list[Decimal] = []
    for cursor in range(start, index + 1):
        item = _eval(expr, rows, cursor)
        if item is None:
            if explicit_window:
                return None
            continue
        values.append(item)
    if not values:
        return None
    if node.name in {"mean", "ts_mean"}:
        return sum(values, Decimal("0")) / Decimal(len(values))
    if node.name in {"sum"}:
        return sum(values, Decimal("0"))
    if node.name == "ts_max":
        return max(values)
    if node.name == "ts_min":
        return min(values)
    if node.name in {"std", "ts_std", "zscore"}:
        spread = _sample_std(values)
        if node.name != "zscore":
            return spread
        last = _eval(expr, rows, index)
        mean = sum(values, Decimal("0")) / Decimal(len(values))
        if last is None or spread is None or spread == 0:
            return None
        return (last - mean) / spread
    raise InvalidHypothesisError(f"unknown window function {node.name!r}")


def _window_size(node: CallOp, *, index: int) -> int | None:
    if node.name in _OPTIONAL_WINDOW and len(node.args) == 1:
        return index + 1
    if len(node.args) != 2:
        raise InvalidHypothesisError(f"{node.name} requires a window length")
    window_node = node.args[1]
    if not isinstance(window_node, Literal):
        raise InvalidHypothesisError(f"{node.name} window must be a numeric literal")
    value = window_node.value
    if value != value.to_integral_value() or value < 1:
        raise InvalidHypothesisError(f"{node.name} window must be an integer >= 1")
    return int(value)


def _sample_std(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum((item - mean) ** 2 for item in values) / Decimal(len(values) - 1)
    if variance < 0:
        return None
    return variance.sqrt()


@dataclass
class _Token:
    kind: str
    value: str
    position: int


class _Parser:
    def __init__(self, formula: str) -> None:
        stripped = formula.strip()
        if not stripped:
            raise InvalidHypothesisError("formula is empty")
        self._tokens = _tokenize(stripped)
        self._index = 0

    def parse(self) -> FactorNode:
        node = self._expr()
        if self._index < len(self._tokens):
            leftover = self._tokens[self._index]
            raise InvalidHypothesisError(
                f"unexpected token {leftover.value!r} at position {leftover.position}"
            )
        return node

    def _expr(self) -> FactorNode:
        node = self._term()
        while self._match("+", "-"):
            op = self._previous().value
            right = self._term()
            node = BinaryOp(op=op, left=node, right=right)
        return node

    def _term(self) -> FactorNode:
        node = self._power()
        while self._match("*", "/"):
            op = self._previous().value
            right = self._power()
            node = BinaryOp(op=op, left=node, right=right)
        return node

    def _power(self) -> FactorNode:
        node = self._unary()
        if self._match("**"):
            right = self._unary()
            node = BinaryOp(op="**", left=node, right=right)
        return node

    def _unary(self) -> FactorNode:
        if self._match("-"):
            return UnaryOp(op="neg", arg=self._unary())
        return self._primary()

    def _primary(self) -> FactorNode:
        if self._match("number"):
            return Literal(value=Decimal(self._previous().value))
        if self._match("ident"):
            name = self._previous().value
            if self._match("("):
                return self._finish_call(name)
            if name not in FEATURE_NAMES:
                raise InvalidHypothesisError(f"unknown feature {name!r}")
            return Feature(name=name)
        if self._match("("):
            node = self._expr()
            self._consume(")", "expected ')'")
            return node
        token = self._peek()
        detail = "end of formula" if token is None else f"{token.value!r}"
        raise InvalidHypothesisError(f"expected expression, got {detail}")

    def _finish_call(self, name: str) -> FactorNode:
        if name in CROSS_SECTIONAL:
            raise InvalidHypothesisError(
                f"{name} is cross-sectional and needs a universe; not available in this lab"
            )
        args: list[FactorNode] = []
        if not self._check(")"):
            args.append(self._expr())
            while self._match(","):
                args.append(self._expr())
        self._consume(")", f"expected ')' after {name}(...)")
        _assert_arity(name, len(args))
        if name in _UNARY_FUNCS:
            return (
                UnaryOp(op=name, arg=args[0])
                if len(args) == 1
                else CallOp(name=name, args=tuple(args))
            )
        return CallOp(name=name, args=tuple(args))

    def _match(self, *kinds: str) -> bool:
        if self._check(*kinds):
            self._index += 1
            return True
        return False

    def _check(self, *kinds: str) -> bool:
        token = self._peek()
        return token is not None and token.kind in kinds

    def _consume(self, kind: str, message: str) -> _Token:
        if self._check(kind):
            self._index += 1
            return self._previous()
        raise InvalidHypothesisError(message)

    def _peek(self) -> _Token | None:
        if self._index >= len(self._tokens):
            return None
        return self._tokens[self._index]

    def _previous(self) -> _Token:
        return self._tokens[self._index - 1]


def _assert_arity(name: str, count: int) -> None:
    if name in _UNARY_FUNCS and count != 1:
        raise InvalidHypothesisError(f"{name} takes 1 argument")
    if name == "clip" and count != 3:
        raise InvalidHypothesisError("clip takes 3 arguments: value, lo, hi")
    if name in {"max", "min", "pow"} and count != 2:
        raise InvalidHypothesisError(f"{name} takes 2 arguments")
    if name in _WINDOW_FUNCS and count != 2:
        raise InvalidHypothesisError(f"{name} takes 2 arguments: expr, window")
    if name in _OPTIONAL_WINDOW and count not in {1, 2}:
        raise InvalidHypothesisError(f"{name} takes 1 or 2 arguments")
    allowed = _UNARY_FUNCS | _WINDOW_FUNCS | _OPTIONAL_WINDOW | {"clip", "max", "min", "pow"}
    if name not in allowed:
        raise InvalidHypothesisError(f"unknown function {name!r}")


def _tokenize(formula: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    length = len(formula)
    while index < length:
        char = formula[index]
        if char.isspace():
            index += 1
            continue
        if formula.startswith("**", index):
            tokens.append(_Token("**", "**", index))
            index += 2
            continue
        if char in "+-*/(),":
            tokens.append(_Token(char, char, index))
            index += 1
            continue
        if char.isdigit() or (char == "." and index + 1 < length and formula[index + 1].isdigit()):
            start = index
            dotted = False
            while index < length and (formula[index].isdigit() or formula[index] == "."):
                if formula[index] == ".":
                    if dotted:
                        raise InvalidHypothesisError(f"invalid number at position {start}")
                    dotted = True
                index += 1
            tokens.append(_Token("number", formula[start:index], start))
            continue
        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < length and (formula[index].isalnum() or formula[index] == "_"):
                index += 1
            tokens.append(_Token("ident", formula[start:index], start))
            continue
        raise InvalidHypothesisError(f"unexpected character {char!r} at position {index}")
    return tokens
