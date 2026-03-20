from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser


@dataclass
class RawSymbol:
    name: str
    kind: str  # function | class | method
    qualified_name: str
    start_line: int
    end_line: int
    start_col: int
    end_col: int


@dataclass
class RawCall:
    caller_qn: str
    callee_hint: str
    line: int


@dataclass
class RawImport:
    module: str
    line: int


@dataclass
class ParsedFile:
    symbols: list[RawSymbol] = field(default_factory=list)
    calls: list[RawCall] = field(default_factory=list)
    imports: list[RawImport] = field(default_factory=list)


_parser: Parser | None = None


def _get_parser() -> Parser:
    global _parser
    if _parser is None:
        _parser = Parser(Language(tspython.language()))
    return _parser


def _node_text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _name_of_def(source: bytes, node: Node) -> str:
    n = node.child_by_field_name("name")
    if n is None:
        return ""
    return _node_text(source, n).strip()


def _call_callee_hint(source: bytes, node: Node) -> str | None:
    fn = node.child_by_field_name("function")
    if fn is None:
        return None
    return _callee_from_expression(source, fn)


def _callee_from_expression(source: bytes, node: Node) -> str:
    t = node.type
    if t == "identifier":
        return _node_text(source, node).strip()
    if t == "attribute":
        attr = node.child_by_field_name("attribute")
        if attr:
            return _node_text(source, attr).strip()
        return _node_text(source, node).strip()
    if t == "subscript":
        val = node.child_by_field_name("value")
        if val:
            return _callee_from_expression(source, val)
    return _node_text(source, node).strip()[:200]


def _walk_imports(source: bytes, node: Node, out: list[RawImport]) -> None:
    t = node.type
    if t == "import_statement":
        for ch in node.children:
            if ch.type == "dotted_name":
                mod = _node_text(source, ch).strip()
                if mod:
                    out.append(RawImport(module=mod, line=ch.start_point[0] + 1))
            elif ch.type == "aliased_import":
                dn = ch.child_by_field_name("name")
                if dn and dn.type == "dotted_name":
                    mod = _node_text(source, dn).strip()
                    if mod:
                        out.append(RawImport(module=mod, line=ch.start_point[0] + 1))
    elif t == "import_from_statement":
        mod_n = node.child_by_field_name("module_name")
        if mod_n is None:
            rel = node.child_by_field_name("relative_import")
            if rel:
                mod = _node_text(source, rel).strip().lstrip(".")
                if mod:
                    out.append(RawImport(module=mod, line=node.start_point[0] + 1))
        else:
            mod = _node_text(source, mod_n).strip()
            if mod:
                out.append(RawImport(module=mod, line=node.start_point[0] + 1))


def _unwrap_definition(node: Node) -> Node:
    if node.type == "decorated_definition":
        for ch in node.children:
            if ch.type in ("function_definition", "class_definition"):
                return ch
    return node


def parse_python_file(path: str, source: bytes) -> ParsedFile:
    parser = _get_parser()
    tree = parser.parse(source)
    out = ParsedFile()
    class_stack: list[str] = []

    def visit(node: Node, current_fn_qn: str | None) -> None:
        nonlocal class_stack
        node = _unwrap_definition(node)
        t = node.type

        if t == "class_definition":
            nm = _name_of_def(source, node)
            prefix = ".".join(class_stack)
            qn = f"{prefix}.{nm}" if prefix and nm else (nm or prefix)
            if nm:
                out.symbols.append(
                    RawSymbol(
                        name=nm,
                        kind="class",
                        qualified_name=qn,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_col=node.start_point[1],
                        end_col=node.end_point[1],
                    )
                )
            if nm:
                class_stack.append(nm)
            body = node.child_by_field_name("body")
            if body:
                for ch in body.children:
                    visit(ch, current_fn_qn)
            if nm:
                class_stack.pop()
            return

        if t == "function_definition":
            nm = _name_of_def(source, node)
            parent_prefix = ".".join(class_stack) if class_stack else ""
            qn = f"{parent_prefix}.{nm}" if parent_prefix and nm else nm
            kind = "method" if class_stack else "function"
            if nm:
                out.symbols.append(
                    RawSymbol(
                        name=nm,
                        kind=kind,
                        qualified_name=qn,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        start_col=node.start_point[1],
                        end_col=node.end_point[1],
                    )
                )
            inner_qn = qn if nm else current_fn_qn
            body = node.child_by_field_name("body")
            if body:
                for ch in body.children:
                    visit(ch, inner_qn)
            return

        if t == "call_expression" and current_fn_qn:
            hint = _call_callee_hint(source, node)
            if hint:
                out.calls.append(
                    RawCall(
                        caller_qn=current_fn_qn,
                        callee_hint=hint,
                        line=node.start_point[0] + 1,
                    )
                )

        _walk_imports(source, node, out.imports)

        for ch in node.children:
            visit(ch, current_fn_qn)

    visit(tree.root_node, None)
    return out
