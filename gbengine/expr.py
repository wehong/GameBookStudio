"""조건식과 값 계산.

스크립트의 `if 금화 >= 3`, `set 체력 -= 2` 같은 식을 안전하게 계산합니다.
Python 문법의 일부만 허용하며(eval을 쓰지 않음), 허용하지 않는 구문은
스크립트를 읽는 시점에 오류로 알려 줍니다.
"""

from __future__ import annotations

import ast
import operator

# 스크립트에서 쓸 수 있는 상수 이름 (Python의 True/False/None 외에 소문자, 한글도 허용)
CONSTANTS = {
    "true": True, "false": False, "none": None,
    "True": True, "False": False, "None": None,
    "참": True, "거짓": False,
}

FUNCTIONS = {"visited", "random"}

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_UNARY = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


class ExprError(Exception):
    pass


class Expr:
    """미리 검사해 둔 식. names = 식이 읽는 변수 이름들, labels = visited()로 참조하는 단락들."""

    __slots__ = ("source", "tree", "names", "labels")

    def __init__(self, source: str):
        self.source = source.strip()
        if not self.source:
            raise ExprError("식이 비어 있습니다.")
        try:
            self.tree = ast.parse(self.source, mode="eval").body
        except SyntaxError:
            raise ExprError(f"식을 이해할 수 없습니다: {self.source}") from None
        self.names: set[str] = set()
        self.labels: set[str] = set()
        self._check(self.tree)

    def _check(self, node):
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                self._check(v)
        elif isinstance(node, ast.UnaryOp):
            if type(node.op) not in _UNARY:
                raise ExprError(f"지원하지 않는 연산입니다: {self.source}")
            self._check(node.operand)
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _BINOPS:
                raise ExprError(f"지원하지 않는 연산입니다: {self.source}")
            self._check(node.left)
            self._check(node.right)
        elif isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) not in _CMPOPS:
                    raise ExprError(f"지원하지 않는 비교입니다: {self.source}")
            self._check(node.left)
            for c in node.comparators:
                self._check(c)
        elif isinstance(node, ast.Name):
            if node.id not in CONSTANTS:
                self.names.add(node.id)
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, str, bool, type(None))):
                raise ExprError(f"지원하지 않는 값입니다: {self.source}")
        elif isinstance(node, ast.Call):
            fname = node.func.id if isinstance(node.func, ast.Name) else None
            if fname not in FUNCTIONS or node.keywords:
                raise ExprError(
                    f"사용할 수 있는 함수는 visited(\"단락\"), random(최소, 최대) 뿐입니다: {self.source}")
            if fname == "visited":
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) \
                        or not isinstance(node.args[0].value, (str, int)):
                    raise ExprError(f'visited는 visited("단락이름") 형태로 써야 합니다: {self.source}')
                self.labels.add(str(node.args[0].value))
            else:
                if len(node.args) != 2:
                    raise ExprError(f"random은 random(최소, 최대) 형태로 써야 합니다: {self.source}")
                for a in node.args:
                    self._check(a)
        else:
            raise ExprError(f"식에 쓸 수 없는 구문이 있습니다: {self.source}")

    def eval(self, ctx: "EvalContext"):
        return _eval(self.tree, ctx)

    def __repr__(self):
        return f"Expr({self.source!r})"


class EvalContext:
    """식 계산에 필요한 정보: 변수, 방문 기록, 난수 발생기."""

    def __init__(self, variables: dict, visited: dict, rng):
        self.variables = variables
        self.visited = visited
        self.rng = rng


def _eval(node, ctx: EvalContext):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        # 아직 정해지지 않은 변수는 0 (거짓)으로 취급
        return ctx.variables.get(node.id, 0)
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for v in node.values:
                result = _eval(v, ctx)
                if not result:
                    return result
            return result
        result = False
        for v in node.values:
            result = _eval(v, ctx)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        return _UNARY[type(node.op)](_eval(node.operand, ctx))
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, ctx), _eval(node.right, ctx)
        try:
            return _BINOPS[type(node.op)](left, right)
        except ZeroDivisionError:
            raise ExprError("0으로 나눌 수 없습니다.") from None
        except TypeError:
            raise ExprError(f"서로 계산할 수 없는 값입니다: {left!r}, {right!r}") from None
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, ctx)
            try:
                ok = _CMPOPS[type(op)](left, right)
            except TypeError:
                raise ExprError(f"서로 비교할 수 없는 값입니다: {left!r}, {right!r}") from None
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        if node.func.id == "visited":
            return ctx.visited.get(str(node.args[0].value), 0)
        lo, hi = int(_eval(node.args[0], ctx)), int(_eval(node.args[1], ctx))
        if lo > hi:
            lo, hi = hi, lo
        return ctx.rng.randint(lo, hi)
    raise ExprError("계산할 수 없는 식입니다.")
