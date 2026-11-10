"""Tree-sitter extraction of symbols, occurrences, and interaction sites.

A missing parser records ``parser_unavailable`` and does not raise.
ERROR and MISSING nodes are counted and not treated as complete syntax.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from py_indexer.structural import (
    EXPRESSION_CHARS,
    NODE_CAP,
    SIGNATURE_CHARS,
    SITE_CAP,
    SYMBOL_CAP,
    clip,
    language_ready,
    loaded_language,
    structural_language,
)

EXTRACT_CALLS = 0

_ROUTE_RECEIVERS = {
    "app",
    "router",
    "route",
    "routes",
    "server",
    "fastify",
    "express",
    "svr",
}
_CLIENT_RECEIVERS = {"axios", "http", "https", "fetch", "client"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_SPAWN_NAMES = {"spawn", "execfile", "execa"}
_SHELL_NAMES = {"exec", "execacommand"}
_LISTEN_NAMES = {"listen", "bind"}
_CONNECT_NAMES = {"connect"}
_GENERIC_STEMS = {"main", "index", "app", "server", "mod", "lib"}


@dataclass
class SymbolRec:
    symbol_id: str
    identity_key: str
    path: str
    language: str
    kind: str
    name: str
    qualified_name: str
    signature: str
    params: str
    scope: list[str]
    anon_ord: int | None = None
    body_hash: str | None = None
    role: str = "decl_and_def"
    param_key: str | None = None
    start_line: int = 1
    start_col: int = 1
    end_line: int = 1
    end_col: int = 1
    start_byte: int = 0
    end_byte: int = 0


@dataclass
class SiteRec:
    path: str
    site_kind: str
    rule_id: str
    resolution: str
    expression_text: str
    payload: dict
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    start_byte: int
    end_byte: int
    enclosing_symbol_id: str | None = None
    http_method: str | None = None
    http_path: str | None = None
    http_suffix: str | None = None
    http_boundary: str | None = None
    http_rev: str | None = None
    dispatch_key: str | None = None
    norm_name: str | None = None
    norm_spec: str | None = None
    norm_tail: str | None = None
    handler_key: str | None = None
    handler_symbol_id: str | None = None
    exec_id: str | None = None
    exec_args_norm: str | None = None
    net_host: str | None = None
    net_port: int | None = None
    net_role: str | None = None
    net_wildcard: int | None = None
    rpc_command: str | None = None
    evidence_truncated: int = 0
    callee_name: str | None = None
    qualifier: str | None = None
    arg_count: int | None = None


@dataclass
class ExtractResult:
    language: str
    status: str
    error_count: int = 0
    truncated: bool = False
    detail: str = ""
    symbols: list[SymbolRec] = field(default_factory=list)
    sites: list[SiteRec] = field(default_factory=list)


def extract_file(path: str, text: str) -> ExtractResult:
    """Extract structural facts for one file. Never raises."""
    global EXTRACT_CALLS
    EXTRACT_CALLS += 1
    lang = structural_language(path)
    if lang is None:
        status = "lexical_only" if path.lower().endswith(".c") else "unsupported"
        detail = (
            ".c is not parsed; .h is parsed with the C++ grammar"
            if status == "lexical_only"
            else ""
        )
        return ExtractResult(language="" if status == "unsupported" else "c", status=status, detail=detail)
    if not language_ready(lang):
        return ExtractResult(
            language=lang,
            status="parser_unavailable",
            detail=f"{lang} parser is not available at the pinned version",
        )
    try:
        return _extract(path, text, lang)
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(language=lang, status="failed", detail=type(exc).__name__)


def _extract(path: str, text: str, lang: str) -> ExtractResult:
    from tree_sitter import Parser

    language = loaded_language(lang)
    parser = Parser(language)
    source = text.encode("utf-8")
    tree = parser.parse(source)
    walk = _Walker(path, lang, source)
    consts = _collect_consts(tree.root_node, source, lang)
    walk.consts = consts
    walk.imports = _collect_named_imports(tree.root_node, source)
    walk.bindings = _collect_const_calls(tree.root_node, source)
    walk.visit(tree.root_node)
    walk.finish()
    status = "ok"
    if walk.errors:
        status = "partial" if walk.symbols or walk.sites else "failed"
    if walk.truncated:
        status = "partial"
    detail = ""
    if walk.errors:
        detail = f"{walk.errors} syntax error node(s) skipped"
    return ExtractResult(
        language=lang,
        status=status,
        error_count=walk.errors,
        truncated=walk.truncated,
        detail=detail,
        symbols=walk.symbols,
        sites=walk.sites,
    )


def _node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _loc(node) -> tuple[int, int, int, int, int, int]:
    return (
        node.start_point[0] + 1,
        node.start_point[1] + 1,
        node.end_point[0] + 1,
        node.end_point[1] + 1,
        node.start_byte,
        node.end_byte,
    )


def _string_value(source: bytes, node) -> str | None:
    if node is None:
        return None
    if node.type in {"string", "string_literal", "interpreted_string_literal"}:
        fragments = [
            _node_text(source, child)
            for child in _named(node)
            if child.type in {"string_fragment", "string_content"}
        ]
        if fragments:
            return "".join(fragments)
        raw = _node_text(source, node)
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'", "`"}:
            return raw[1:-1]
        return None
    if node.type in {"template_string", "template_literal"}:
        if any(child.type in {"template_substitution", "substitution"} for child in _named(node)):
            return None
        fragments = [
            _node_text(source, child)
            for child in _named(node)
            if child.type in {"string_fragment", "template_content"}
        ]
        return "".join(fragments) if fragments else ""
    return None


def _named(node):
    return [node.named_child(i) for i in range(node.named_child_count)]


def _collect_consts(root, source: bytes, lang: str) -> dict[str, str]:
    assigned: set[str] = set()
    found: dict[str, str] = {}

    def walk(node) -> None:
        if node.type in {"assignment_expression", "assignment_expression"} or (
            node.type == "assignment_expression"
        ):
            left = node.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                assigned.add(_node_text(source, left))
        if lang in {"javascript", "typescript", "tsx"} and node.type == "lexical_declaration":
            kind = _node_text(source, node).lstrip().split(" ", 1)[0]
            if kind == "const":
                for decl in _named(node):
                    if decl.type != "variable_declarator":
                        continue
                    name = decl.child_by_field_name("name")
                    value = decl.child_by_field_name("value")
                    if name is not None and name.type == "identifier" and value is not None:
                        literal = _string_value(source, value)
                        if literal is None and value.type in {"number", "number_literal"}:
                            literal = _node_text(source, value)
                        if literal is not None:
                            found[_node_text(source, name)] = literal
        if lang == "cpp" and node.type == "declaration":
            header = _node_text(source, node)
            if header.lstrip().startswith("const ") or header.lstrip().startswith("constexpr "):
                for decl in _named(node):
                    if decl.type != "init_declarator":
                        continue
                    name = decl.child_by_field_name("declarator")
                    value = decl.child_by_field_name("value")
                    if name is not None and name.type == "identifier" and value is not None:
                        literal = _string_value(source, value)
                        if literal is not None:
                            found[_node_text(source, name)] = literal
        if lang == "rust" and node.type == "const_item":
            name = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if name is not None and value is not None:
                literal = _string_value(source, value)
                if literal is not None:
                    found[_node_text(source, name)] = literal
        for child in node.children:
            walk(child)

    walk(root)
    for name in assigned:
        found.pop(name, None)
    return found


class _Walker:
    def __init__(self, path: str, lang: str, source: bytes) -> None:
        self.path = path
        self.lang = lang
        self.source = source
        self.scope: list[tuple[str, str]] = []
        self.symbols: list[SymbolRec] = []
        self.sites: list[SiteRec] = []
        self.errors = 0
        self.nodes = 0
        self.truncated = False
        self.consts: dict[str, str] = {}
        self.imports: dict[str, tuple[str, str]] = {}
        self.bindings: dict[str, str] = {}
        self.http_tables: set[str] = set()
        self._enclosing: list[str] = []
        self._anon: dict[tuple, int] = {}
        self._dup: dict[tuple, int] = {}

    def finish(self) -> None:
        for site in self.sites:
            table = site.payload.get("table") if isinstance(site.payload, dict) else None
            if site.site_kind == "dispatch" and table in self.http_tables and site.dispatch_key:
                site.site_kind = "http_route"
                site.rule_id = "http.cpp.table"
                site.http_path = site.dispatch_key
                site.http_rev = site.dispatch_key[::-1]
                site.resolution = "candidate"
                promoted = {
                    "classification": "http_route",
                    "table": table,
                    "handler": site.handler_key or "",
                    "path_known": True,
                }
                if "handler_scope" in site.payload:
                    promoted["handler_scope"] = site.payload["handler_scope"]
                    promoted["handler_absolute"] = bool(site.payload.get("handler_absolute"))
                site.payload = promoted

    def visit(self, node) -> None:
        if self.truncated:
            return
        self.nodes += 1
        if self.nodes > NODE_CAP or len(self.symbols) > SYMBOL_CAP or len(self.sites) > SITE_CAP:
            self.truncated = True
            return
        if node.type == "ERROR" or node.is_missing:
            self.errors += 1
            return
        handler = _HANDLERS.get((self.lang, node.type)) or _HANDLERS.get(("*", node.type))
        if handler is not None and handler(self, node):
            return
        for child in node.children:
            self.visit(child)

    def scope_labels(self) -> list[str]:
        return [f"{kind}:{name}" for kind, name in self.scope]

    def qualified(self, name: str) -> str:
        parts = [item[1] for item in self.scope] + [name]
        sep = "." if self.lang in {"javascript", "typescript", "tsx"} else "::"
        return sep.join(parts)

    def add_symbol(
        self,
        node,
        *,
        kind: str,
        name: str,
        params: str,
        signature: str,
        role: str,
        body_hash: str | None = None,
        anon: bool = False,
        param_key: str | None = None,
    ) -> str:
        signature, sig_cut = clip(_norm(signature), SIGNATURE_CHARS)
        params = _norm(params)[:SIGNATURE_CHARS]
        scope = self.scope_labels()
        anon_ord = None
        if anon or not name:
            key = (tuple(scope), params, body_hash or "")
            anon_ord = self._anon.get(key, 0)
            self._anon[key] = anon_ord + 1
            if not name:
                name = f"<anonymous:{anon_ord}>"
        else:
            key = (tuple(scope), kind, name, params)
            ordinal = self._dup.get(key, 0)
            self._dup[key] = ordinal + 1
            if ordinal:
                anon_ord = ordinal
        payload = {
            "v": 1,
            "lang": self.lang,
            "path": self.path,
            "kind": kind,
            "scope": scope,
            "name": name,
            "signature": params,
            "anon": None
            if anon_ord is None and body_hash is None
            else {"body": body_hash, "ord": anon_ord or 0},
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        symbol_id = "s1_" + digest[:24]
        loc = _loc(node)
        self.symbols.append(
            SymbolRec(
                symbol_id=symbol_id,
                identity_key=digest,
                path=self.path,
                language=self.lang,
                kind=kind,
                name=name,
                qualified_name=self.qualified(name),
                signature=signature,
                params=params,
                scope=scope,
                anon_ord=anon_ord,
                body_hash=body_hash,
                role=role,
                param_key=param_key,
                start_line=loc[0],
                start_col=loc[1],
                end_line=loc[2],
                end_col=loc[3],
                start_byte=loc[4],
                end_byte=loc[5],
            )
        )
        if sig_cut:
            self.truncated = True
        return symbol_id

    def add_site(self, node, **kwargs) -> None:
        loc = _loc(node)
        expr, cut = clip(_norm(kwargs.pop("expression_text", _node_text(self.source, node))), EXPRESSION_CHARS)
        self.sites.append(
            SiteRec(
                path=self.path,
                expression_text=expr,
                evidence_truncated=1 if cut else 0,
                start_line=loc[0],
                start_col=loc[1],
                end_line=loc[2],
                end_col=loc[3],
                start_byte=loc[4],
                end_byte=loc[5],
                enclosing_symbol_id=self._enclosing[-1] if self._enclosing else None,
                **kwargs,
            )
        )

    def eval_expr(self, node) -> str | None:
        if node is None:
            return None
        literal = _string_value(self.source, node)
        if literal is not None:
            return literal
        if node.type in {"number", "number_literal"}:
            return _node_text(self.source, node)
        if node.type == "identifier":
            return self.consts.get(_node_text(self.source, node))
        if node.type == "binary_expression":
            op = node.child_by_field_name("operator")
            if op is not None and _node_text(self.source, op) == "+":
                left = self.eval_expr(node.child_by_field_name("left"))
                right = self.eval_expr(node.child_by_field_name("right"))
                if left is not None and right is not None:
                    return left + right
        return None

    def with_scope(self, kind: str, name: str, node, body) -> None:
        self.scope.append((kind, name))
        if body is not None:
            self.visit(body)
        self.scope.pop()

    def with_function(self, symbol_id: str, body) -> None:
        self._enclosing.append(symbol_id)
        if body is not None:
            self.visit(body)
        self._enclosing.pop()


def _params_of(source: bytes, node) -> str:
    for field in ("parameters", "parameters"):
        found = node.child_by_field_name(field)
        if found is not None:
            return _norm(_node_text(source, found))
    for child in _named(node):
        if child.type in {"parameter_list", "parameters", "formal_parameters"}:
            return _norm(_node_text(source, child))
    return "()"


def _cpp_name(source: bytes, declarator) -> tuple[str, list[tuple[str, str]]]:
    """Return (name, extra scope) from a C++ declarator."""
    node = declarator
    extra: list[tuple[str, str]] = []
    while node is not None and node.type in {
        "pointer_declarator",
        "reference_declarator",
        "qualified_identifier",
        "function_declarator",
        "parenthesized_declarator",
    }:
        if node.type == "qualified_identifier":
            scope = node.child_by_field_name("scope")
            name = node.child_by_field_name("name")
            if scope is not None:
                extra.append(("class", _node_text(source, scope)))
            if name is not None:
                return _node_text(source, name), extra
        node = node.child_by_field_name("declarator") or (
            node.named_child(0) if node.named_child_count else None
        )
    if declarator is None:
        return "", extra
    if declarator.type in {"identifier", "field_identifier", "type_identifier", "operator_name"}:
        return _node_text(source, declarator), extra
    name = declarator.child_by_field_name("declarator")
    if name is not None and name.type in {"identifier", "field_identifier", "operator_name"}:
        return _node_text(source, name), extra
    return _node_text(source, declarator).split("(")[0].strip(), extra


def _handle_cpp_namespace(walk: _Walker, node) -> bool:
    name_node = node.child_by_field_name("name")
    name = _node_text(walk.source, name_node) if name_node is not None else "<anonymous>"
    body = node.child_by_field_name("body")
    walk.scope.append(("namespace", name))
    if body is not None:
        walk.visit(body)
    walk.scope.pop()
    return True


def _handle_cpp_class(walk: _Walker, node) -> bool:
    name_node = node.child_by_field_name("name")
    name = _node_text(walk.source, name_node) if name_node is not None else "<anonymous>"
    kind = "struct" if _node_text(walk.source, node).lstrip().startswith("struct") else "class"
    symbol = node
    walk.add_symbol(
        symbol,
        kind=kind,
        name=name,
        params="",
        signature=_norm(_node_text(walk.source, node).split("{", 1)[0]),
        role="decl_and_def",
    )
    body = node.child_by_field_name("body")
    walk.scope.append((kind, name))
    if body is not None:
        walk.visit(body)
    walk.scope.pop()
    return True


def _handle_cpp_function(walk: _Walker, node) -> bool:
    declarator = node.child_by_field_name("declarator")
    params = _params_of(walk.source, declarator or node)
    name, extra = _cpp_name(walk.source, declarator)
    for item in extra:
        walk.scope.append(item)
    kind = "function"
    if name.startswith("operator"):
        kind = "operator"
    elif walk.scope and name == walk.scope[-1][1]:
        kind = "constructor"
    body = node.child_by_field_name("body")
    _note_http_tables(walk, body)
    role = "definition" if body is not None else "declaration"
    signature = _norm(_node_text(walk.source, node if body is None else declarator or node))
    symbol_id = walk.add_symbol(
        node,
        kind=kind,
        name=name or "<anonymous>",
        params=params,
        signature=signature,
        role=role,
        param_key=_cpp_param_key(walk.source, declarator),
    )
    if name == "main" and body is not None:
        stem = Path(walk.path).stem
        walk.add_site(
            node,
            site_kind="process_entry",
            rule_id="proc.entry",
            resolution="resolved",
            expression_text=name,
            payload={"stem": stem},
            exec_id=None if stem.lower() in _GENERIC_STEMS else stem,
        )
    walk.with_function(symbol_id, body)
    for _ in extra:
        walk.scope.pop()
    return True


def _handle_cpp_declaration(walk: _Walker, node) -> bool:
    if _record_dispatch_table(walk, node):
        return True
    declarator = node.child_by_field_name("declarator")
    if declarator is None or declarator.type != "function_declarator":
        return False
    params = _params_of(walk.source, declarator)
    name, extra = _cpp_name(walk.source, declarator)
    for item in extra:
        walk.scope.append(item)
    kind = "constructor" if walk.scope and name == walk.scope[-1][1] else "function"
    if name.startswith("operator"):
        kind = "operator"
    walk.add_symbol(
        node,
        kind=kind,
        name=name or "<anonymous>",
        params=params,
        signature=_norm(_node_text(walk.source, node)),
        role="declaration",
        param_key=_cpp_param_key(walk.source, declarator),
    )
    for _ in extra:
        walk.scope.pop()
    return True


def _handle_js_function(walk: _Walker, node) -> bool:
    name_node = node.child_by_field_name("name")
    name = _node_text(walk.source, name_node) if name_node is not None else ""
    params = _params_of(walk.source, node)
    body = node.child_by_field_name("body")
    body_hash = None
    anon = not name
    if anon and body is not None:
        body_hash = hashlib.sha256(_node_text(walk.source, body).encode("utf-8")).hexdigest()[:16]
    symbol_id = walk.add_symbol(
        node,
        kind="function",
        name=name,
        params=params,
        signature=_norm(_node_text(walk.source, node).split("{", 1)[0]),
        role="decl_and_def",
        body_hash=body_hash,
        anon=anon,
    )
    fact = _slash_normalizer_fact(body, walk.source)
    if fact and name:
        walk._enclosing.append(symbol_id)
        walk.add_site(
            node,
            site_kind="normalizer",
            rule_id="http.slash_normalizer",
            resolution="candidate",
            expression_text=name,
            payload={"empty_unseparated": fact["empty_unseparated"], "boundary": "conditional_slash"},
        )
        walk._enclosing.pop()
    walk.scope.append(("function", name or symbol_id))
    walk.with_function(symbol_id, body)
    walk.scope.pop()
    return True


def _handle_js_arrow(walk: _Walker, node) -> bool:
    params = _params_of(walk.source, node)
    body = node.child_by_field_name("body")
    body_hash = hashlib.sha256(_node_text(walk.source, body or node).encode("utf-8")).hexdigest()[:16]
    # Name comes from a parent variable declarator when present.
    name = ""
    parent = node.parent
    if parent is not None and parent.type == "variable_declarator":
        name_node = parent.child_by_field_name("name")
        if name_node is not None and name_node.type == "identifier":
            name = _node_text(walk.source, name_node)
    symbol_id = walk.add_symbol(
        node,
        kind="function",
        name=name,
        params=params,
        signature=_norm(_node_text(walk.source, node).split("=>", 1)[0] + "=>"),
        role="decl_and_def",
        body_hash=body_hash,
        anon=not name,
    )
    walk.scope.append(("function", name or symbol_id))
    if body is not None and body.type == "statement_block":
        walk.with_function(symbol_id, body)
    else:
        walk.with_function(symbol_id, None)
        if body is not None:
            walk.visit(body)
    walk.scope.pop()
    return True


def _handle_js_class(walk: _Walker, node) -> bool:
    name_node = node.child_by_field_name("name")
    name = _node_text(walk.source, name_node) if name_node is not None else ""
    walk.add_symbol(
        node,
        kind="class",
        name=name or "<anonymous>",
        params="",
        signature=_norm(_node_text(walk.source, node).split("{", 1)[0]),
        role="decl_and_def",
        anon=not name,
    )
    body = node.child_by_field_name("body")
    walk.scope.append(("class", name or "<anonymous>"))
    if body is not None:
        walk.visit(body)
    walk.scope.pop()
    return True


def _handle_import(walk: _Walker, node) -> bool:
    source_node = node.child_by_field_name("source")
    spec = walk.eval_expr(source_node) or ""
    names = []
    clause = node.child_by_field_name("source")
    for child in _named(node):
        if child.type == "import_clause":
            for spec_node in _named(child):
                if spec_node.type == "import_specifier":
                    exported = spec_node.child_by_field_name("name")
                    local = spec_node.child_by_field_name("alias") or exported
                    if exported is not None and local is not None:
                        names.append(
                            {
                                "exported": _node_text(walk.source, exported),
                                "local": _node_text(walk.source, local),
                            }
                        )
                elif spec_node.type == "identifier":
                    names.append(
                        {
                            "exported": "default",
                            "local": _node_text(walk.source, spec_node),
                        }
                    )
    walk.add_site(
        node,
        site_kind="import",
        rule_id="bind.import",
        resolution="unresolved" if not spec.startswith(".") else "candidate",
        expression_text=_node_text(walk.source, node),
        payload={"specifier": spec, "names": names},
    )
    _ = clause
    return True


def _handle_call(walk: _Walker, node) -> bool:
    func = node.child_by_field_name("function")
    args = node.child_by_field_name("arguments")
    arg_nodes = _named(args) if args is not None else []
    values = [walk.eval_expr(arg) for arg in arg_nodes]
    name, receiver, qualifier = _callee(walk, func)
    lower = name.lower()
    if _maybe_http(walk, node, name, receiver, lower, arg_nodes, values):
        return True
    if _maybe_process(walk, node, lower, arg_nodes, values):
        _walk_args(walk, arg_nodes)
        return True
    if _maybe_net(walk, node, lower, receiver, arg_nodes, values):
        _walk_args(walk, arg_nodes)
        return True
    if _maybe_rpc_write(walk, node, name, receiver, values):
        _walk_args(walk, arg_nodes)
        return True
    if lower in {"strcmp", "strncmp"} and len(values) >= 2 and values[1]:
        command = values[1]
        if _command_token(command):
            walk.add_site(
                node,
                site_kind="rpc_dispatch",
                rule_id="rpc.dispatch.arm",
                resolution="candidate",
                expression_text=_node_text(walk.source, node),
                payload={"command": command},
                rpc_command=command,
            )
            return True
    resolution = "unresolved"
    rule_id = "lang.call"
    if func is not None and func.type == "identifier":
        rule_id = "lang.call"
    elif qualifier:
        rule_id = "bind.qualified"
    else:
        rule_id = "lang.call"
        resolution = "unresolved"
    walk.add_site(
        node,
        site_kind="call",
        rule_id=rule_id,
        resolution=resolution,
        expression_text=_node_text(walk.source, node),
        payload={
            "callee": name,
            "receiver": receiver,
            "qualifier": qualifier,
            "args": len(arg_nodes),
        },
        callee_name=name,
        qualifier=qualifier,
        arg_count=len(arg_nodes),
    )
    _walk_args(walk, arg_nodes)
    return True


def _split_qualified_call(source: bytes, func) -> tuple[str, str]:
    """Split a qualified call into the callee name and its lexical qualifier.

    A leading ``::`` stays on the qualifier so absolute lookup does not become
    a relative name. Nested ``a::b::run`` keeps qualifier ``a::b``.
    """
    leaf = func
    while leaf is not None and leaf.type in {"qualified_identifier", "scoped_identifier"}:
        nxt = leaf.child_by_field_name("name")
        if nxt is None:
            break
        if nxt.type in {"qualified_identifier", "scoped_identifier"}:
            leaf = nxt
            continue
        name = _node_text(source, nxt)
        raw = _node_text(source, func)
        suffix = "::" + name
        if not raw.endswith(suffix):
            return name, ""
        qualifier = raw[: -len(suffix)]
        if raw.startswith("::") and not qualifier.startswith("::"):
            qualifier = "::"
        return name, qualifier
    raw = _node_text(source, func)
    name = raw.split("::")[-1]
    return name, raw if "::" in raw else ""


def _callee(walk: _Walker, func) -> tuple[str, str, str]:
    if func is None:
        return "", "", ""
    if func.type in {"identifier", "field_identifier", "property_identifier"}:
        return _node_text(walk.source, func), "", ""
    if func.type == "member_expression":
        prop = func.child_by_field_name("property")
        obj = func.child_by_field_name("object")
        name = _node_text(walk.source, prop) if prop is not None else ""
        receiver = ""
        if obj is not None and obj.type == "identifier":
            receiver = _node_text(walk.source, obj)
        elif obj is not None:
            receiver = _node_text(walk.source, obj)
        return name, receiver, ""
    if func.type == "field_expression":
        name_node = func.child_by_field_name("field") or func.child_by_field_name("name")
        scope = func.child_by_field_name("argument") or func.child_by_field_name("scope") or func.child_by_field_name("object")
        name = _node_text(walk.source, name_node) if name_node is not None else _node_text(walk.source, func).split(".")[-1]
        qualifier = _node_text(walk.source, scope) if scope is not None else ""
        receiver = qualifier.split("::")[-1].split(".")[-1] if qualifier else ""
        return name, receiver, qualifier
    if func.type in {"scoped_identifier", "qualified_identifier"}:
        name, qualifier = _split_qualified_call(walk.source, func)
        receiver = qualifier.split("::")[-1].split(".")[-1] if qualifier else ""
        return name, receiver, qualifier
    raw = _node_text(walk.source, func)
    return raw.split("::")[-1].split(".")[-1], "", raw if "::" in raw or "." in raw else ""


_LITERAL_SUFFIX = re.compile(r"^/(?:[A-Za-z0-9._~-]+)(?:/[A-Za-z0-9._~-]+)*$")
_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]+$")


def _template_tail(source: bytes, node):
    """Return (static tail, substitution node) for one leading substitution."""
    if node is None or node.type != "template_string":
        return None
    parts = []
    for child in node.children:
        if child.type == "template_substitution":
            parts.append(("sub", child))
        elif child.type == "string_fragment":
            parts.append(("frag", child))
    if sum(1 for kind, _ in parts if kind == "sub") != 1:
        return None
    if not parts or parts[0][0] != "sub":
        return None
    tail = "".join(_node_text(source, child) for kind, child in parts if kind == "frag")
    tail = tail.split("?", 1)[0].split("#", 1)[0]
    sub = next(child for kind, child in parts if kind == "sub")
    return tail, sub


def _substitution_expr(node):
    for child in _named(node):
        return child
    return None


def _dependency_for_expr(walk: _Walker, expr) -> tuple[str, str] | None:
    """Return (exported name, relative spec or '') for one callee hop."""
    callee = ""
    if expr is None:
        return None
    if expr.type == "identifier":
        callee = walk.bindings.get(_node_text(walk.source, expr), "")
        if not callee:
            return None
    elif expr.type == "call_expression":
        func = expr.child_by_field_name("function")
        if func is None or func.type != "identifier":
            return None
        callee = _node_text(walk.source, func)
    else:
        return None
    if callee in walk.imports:
        exported, spec = walk.imports[callee]
        if not spec.startswith("."):
            return None
        return exported, spec
    return callee, ""


def _record_partial_url(walk: _Walker, node, template, method: str) -> bool:
    found = _template_tail(walk.source, template)
    if found is None:
        return False
    tail, sub = found
    expr = _substitution_expr(sub)
    payload = {"method": method, "path_known": False, "base": "unresolved"}
    if _LITERAL_SUFFIX.fullmatch(tail):
        walk.add_site(
            node,
            site_kind="http_client",
            rule_id="http.js.client",
            resolution="candidate",
            expression_text=_node_text(walk.source, node),
            payload={**payload, "suffix": tail, "boundary": "literal_slash"},
            http_method=method,
            http_suffix=tail,
            http_boundary="literal_slash",
        )
        return True
    if _SEGMENT.fullmatch(tail):
        dep = _dependency_for_expr(walk, expr)
        if dep is None:
            return False
        name, spec = dep
        walk.add_site(
            node,
            site_kind="http_client",
            rule_id="http.js.client",
            resolution="unresolved",
            expression_text=_node_text(walk.source, node),
            payload={**payload, "tail": tail, "normalizer": name, "boundary": "conditional_slash"},
            http_method=method,
            norm_name=name,
            norm_spec=spec,
            norm_tail=tail,
        )
        return True
    return False


def _slash_normalizer_fact(body, source: bytes) -> dict | None:
    """Recognize `endsWith("/") ? value : value + "/"` plus an optional empty return."""
    if body is None or body.type != "statement_block":
        return None
    empty = False
    slash = False
    for stmt in _named(body):
        if stmt.type == "if_statement" and _empty_input_return(stmt, source):
            empty = True
        if stmt.type == "return_statement" and _slash_ternary(stmt, source):
            slash = True
    if not slash:
        return None
    return {"empty_unseparated": empty}


def _empty_input_return(stmt, source: bytes) -> bool:
    cond = stmt.child_by_field_name("condition")
    cons = stmt.child_by_field_name("consequence")
    ident = _unwrapped(cond)
    if ident is None or ident.type != "unary_expression":
        return False
    inner = _named(ident)
    if len(inner) != 1 or inner[0].type != "identifier":
        return False
    name = _node_text(source, inner[0])
    ret = cons
    if ret is not None and ret.type != "return_statement":
        return False
    if ret is None:
        return False
    value = _named(ret)
    return len(value) == 1 and value[0].type == "identifier" and _node_text(source, value[0]) == name


def _slash_ternary(stmt, source: bytes) -> bool:
    expr = _named(stmt)
    if len(expr) != 1 or expr[0].type != "ternary_expression":
        return False
    tern = expr[0]
    cond = tern.child_by_field_name("condition") or (tern.named_child(0) if tern.named_child_count else None)
    if cond is None or cond.type != "call_expression":
        return False
    func = cond.child_by_field_name("function")
    if func is None or func.type != "member_expression":
        return False
    prop = func.child_by_field_name("property")
    if prop is None or _node_text(source, prop) != "endsWith":
        return False
    args = _named(cond.child_by_field_name("arguments"))
    if len(args) != 1 or _string_value(source, args[0]) != "/":
        return False
    receiver = func.child_by_field_name("object")
    if receiver is None or receiver.type != "identifier":
        return False
    recv = _node_text(source, receiver)
    parts = [child for child in tern.children if child.type in {"identifier", "template_string"}]
    if len(parts) != 2:
        return False
    if parts[0].type != "identifier" or _node_text(source, parts[0]) != recv:
        return False
    tail = _template_tail(source, parts[1])
    if tail is None or tail[0] != "/":
        return False
    inner = _substitution_expr(tail[1])
    return inner is not None and inner.type == "identifier" and _node_text(source, inner) == recv


def _unwrapped(node):
    while node is not None and node.type == "parenthesized_expression" and node.named_child_count:
        node = node.named_child(0)
    return node


def _collect_named_imports(root, source: bytes) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}

    def walk(node) -> None:
        if node.type == "import_statement":
            spec = ""
            for child in _named(node):
                if child.type == "string":
                    spec = _string_value(source, child) or ""
            for spec_node in _import_specifiers(node):
                idents = [child for child in _named(spec_node) if child.type == "identifier"]
                if not idents:
                    continue
                exported = _node_text(source, idents[0])
                local = _node_text(source, idents[-1])
                found[local] = (exported, spec)
        for child in node.children:
            walk(child)

    walk(root)
    return found


def _import_specifiers(node) -> list:
    found = []

    def walk(current) -> None:
        if current.type == "import_specifier":
            found.append(current)
            return
        for child in current.children:
            walk(child)

    walk(node)
    return found


def _collect_const_calls(root, source: bytes) -> dict[str, str]:
    found: dict[str, str] = {}
    blocked: set[str] = set()

    def walk(node) -> None:
        if node.type == "assignment_expression":
            left = node.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                blocked.add(_node_text(source, left))
        if node.type == "lexical_declaration":
            kind = _node_text(source, node).lstrip().split(" ", 1)[0]
            if kind == "const":
                for decl in _named(node):
                    if decl.type != "variable_declarator":
                        continue
                    name = decl.child_by_field_name("name")
                    value = decl.child_by_field_name("value")
                    if name is None or name.type != "identifier" or value is None:
                        continue
                    if value.type == "call_expression":
                        func = value.child_by_field_name("function")
                        if func is not None and func.type == "identifier":
                            found[_node_text(source, name)] = _node_text(source, func)
        for child in node.children:
            walk(child)

    walk(root)
    for name in blocked:
        found.pop(name, None)
    return found


def _record_dispatch_table(walk: _Walker, node) -> bool:
    table, entries = _dispatch_entries(walk.source, node)
    if not table or not entries:
        return False
    for key, handler, entry in entries:
        text, absolute = handler
        walk.add_site(
            entry,
            site_kind="dispatch",
            rule_id="dispatch.table",
            resolution="candidate",
            expression_text=key,
            payload={
                "classification": "dispatch",
                "table": table,
                "handler": text,
                "handler_scope": walk.scope_labels(),
                "handler_absolute": absolute,
                "reason": "slash-keyed member dispatch; HTTP request-path lookup not established",
            },
            dispatch_key=key,
            handler_key=text,
        )
    return True


def _dispatch_entries(source: bytes, node):
    declarator = None
    for child in _named(node):
        if child.type == "init_declarator":
            declarator = child
            break
    if declarator is None:
        return "", []
    name_node = declarator.child_by_field_name("declarator")
    value = declarator.child_by_field_name("value")
    table = _leaf_name(source, name_node)
    if not table or value is None or value.type != "initializer_list":
        return "", []
    entries = []
    for item in _named(value):
        if item.type != "initializer_list":
            continue
        kids = _named(item)
        if not kids or kids[0].type != "string_literal":
            continue
        key = _string_value(source, kids[0]) or ""
        if not key.startswith("/") or not _LITERAL_SUFFIX.fullmatch(key):
            continue
        handler = _member_pointer(source, item)
        if handler is None:
            continue
        entries.append((key, handler, item))
    return table, entries


def _leaf_name(source: bytes, node) -> str:
    if node is None:
        return ""
    if node.type in {"identifier", "field_identifier", "type_identifier"}:
        return _node_text(source, node)
    if node.type == "qualified_identifier":
        name = node.child_by_field_name("name")
        return _node_text(source, name) if name is not None else ""
    found = ""
    for child in node.children:
        if child.type in {"identifier", "field_identifier"}:
            found = _node_text(source, child)
    return found


def _member_pointer(source: bytes, node) -> tuple[str, bool] | None:
    found: tuple[str, bool] | None = None

    def walk(current) -> None:
        nonlocal found
        if found is not None:
            return
        if current.type == "pointer_expression":
            target = current.named_child(0) if current.named_child_count else None
            if target is not None and target.type == "qualified_identifier":
                text = _qualified_name(source, target)
                if text and "placeholders" not in text:
                    absolute = bool(target.child_count and target.child(0).type == "::")
                    found = (text, absolute)
                    return
        for child in current.children:
            walk(child)

    walk(node)
    return found


def _cpp_param_key(source: bytes, declarator) -> str | None:
    """Parameter structure with declared names removed. None means uncertain."""
    if declarator is None or declarator.type != "function_declarator":
        return None
    params = None
    quals: list[str] = []
    for child in declarator.children:
        if child.type == "parameter_list":
            params = child
        elif child.type in {"type_qualifier", "ref_qualifier"}:
            quals.append(_node_text(source, child))
    if params is None:
        return None
    body = _cpp_type_structure(source, params)
    if body is None:
        return None
    template = _cpp_template_suffix(source, declarator)
    if template is None:
        return None
    key = body + template
    if quals:
        key += " " + "".join(quals)
    return key


def _cpp_template_suffix(source: bytes, declarator) -> str | None:
    """Return template arguments, '' when absent, or None when uncertain."""
    found: list[str] = []

    def walk(node) -> bool:
        if node.type == "template_argument_list":
            part = _cpp_type_structure(source, node)
            if part is None:
                return False
            found.append(part)
            return True
        if node.type == "parameter_list":
            return True
        for child in node.children:
            if not walk(child):
                return False
        return True

    for child in declarator.children:
        if child.type == "parameter_list":
            break
        if not walk(child):
            return None
    return "".join(found)


def _cpp_type_structure(source: bytes, node) -> str | None:
    kind = node.type
    if kind == "identifier":
        return ""
    if kind in {"*", "&", "&&", "::", "(", ")", "[", "]", "<", ">", ",", ";"}:
        return ""
    if kind in {
        "type_qualifier",
        "primitive_type",
        "type_identifier",
        "namespace_identifier",
        "number_literal",
        "placeholder_type_specifier",
        "sized_type_specifier",
        "decltype",
    }:
        return _node_text(source, node)
    if kind in {"pointer_declarator", "abstract_pointer_declarator"}:
        inner = _cpp_join(source, node)
        return None if inner is None else "*" + inner
    if kind in {"reference_declarator", "abstract_reference_declarator"}:
        raw = _node_text(source, node).lstrip()
        if raw.startswith("&&"):
            op = "&&"
        elif raw.startswith("&"):
            op = "&"
        else:
            return None
        inner = _cpp_join(source, node)
        return None if inner is None else op + inner
    if kind == "variadic_declarator":
        return "..."
    if kind == "array_declarator":
        inner = _cpp_join(source, node)
        return None if inner is None else inner + "[]"
    if kind in {
        "parameter_list",
        "template_argument_list",
        "parameter_declaration",
        "optional_parameter_declaration",
        "variadic_parameter_declaration",
        "type_descriptor",
        "qualified_identifier",
        "template_type",
        "parenthesized_declarator",
        "function_declarator",
        "abstract_function_declarator",
    }:
        inner = _cpp_join(source, node)
        if inner is None:
            return None
        if kind == "parameter_list":
            return "(" + inner + ")"
        if kind == "template_argument_list":
            return "<" + inner + ">"
        return inner
    return None


def _cpp_join(source: bytes, node) -> str | None:
    parts: list[str] = []
    for child in node.children:
        if child.type in {"(", ")", "[", "]", "<", ">", ",", ";", "comment"}:
            continue
        if child.type == "::":
            parts.append("::")
            continue
        part = _cpp_type_structure(source, child)
        if part is None:
            return None
        if part:
            parts.append(part)
    if node.type in {"parameter_list", "template_argument_list"}:
        kept = []
        for child in _named(node):
            part = _cpp_type_structure(source, child)
            if part is None:
                return None
            kept.append(part)
        return ",".join(kept)
    return "".join(parts)


def _qualified_name(source: bytes, node) -> str:
    parts = []
    for child in node.children:
        if child.type == "::":
            continue
        if child.type in {"namespace_identifier", "identifier", "type_identifier", "field_identifier"}:
            parts.append(_node_text(source, child))
        elif child.type == "qualified_identifier":
            nested = _qualified_name(source, child)
            if nested:
                parts.append(nested)
    return "::".join(parts)


def _note_http_tables(walk: _Walker, body) -> None:
    if body is None:
        return
    urls: set[str] = set()

    def walk_node(current) -> None:
        if current.type in {"declaration", "init_declarator"}:
            name = ""
            value = None
            if current.type == "init_declarator":
                name = _leaf_name(walk.source, current.child_by_field_name("declarator"))
                value = current.child_by_field_name("value")
            else:
                for child in _named(current):
                    if child.type == "init_declarator":
                        name = _leaf_name(walk.source, child.child_by_field_name("declarator"))
                        value = child.child_by_field_name("value")
            if name and _is_get_url_call(walk.source, value):
                urls.add(name)
        if current.type == "call_expression":
            func = current.child_by_field_name("function")
            args = current.child_by_field_name("arguments")
            if func is not None and func.type in {"field_expression", "qualified_identifier"}:
                field = func.child_by_field_name("field") or func.child_by_field_name("name")
                obj = func.child_by_field_name("argument") or func.child_by_field_name("scope")
                if field is not None and _node_text(walk.source, field) == "find" and obj is not None:
                    table = _leaf_name(walk.source, obj)
                    arg = _named(args)[0] if args is not None and _named(args) else None
                    if table and _uses_request_url(walk.source, arg, urls):
                        walk.http_tables.add(table)
        for child in current.children:
            walk_node(child)

    walk_node(body)


def _is_get_url_call(source: bytes, node) -> bool:
    if node is None or node.type != "call_expression":
        return False
    func = node.child_by_field_name("function")
    if func is None or func.type not in {"field_expression", "qualified_identifier"}:
        return False
    field = func.child_by_field_name("field") or func.child_by_field_name("name")
    return field is not None and _node_text(source, field) == "getUrl"


def _uses_request_url(source: bytes, node, urls: set[str]) -> bool:
    if node is None:
        return False
    if node.type == "identifier" and _node_text(source, node) in urls:
        return True
    return _is_get_url_call(source, node)


def _maybe_http(walk, node, name, receiver, lower, arg_nodes, values) -> bool:
    if lower not in _HTTP_METHODS and name != "fetch":
        return False
    if name == "fetch":
        target = values[0] if values else None
        method = _object_method(walk, arg_nodes[1]) if len(arg_nodes) >= 2 else None
        arg0 = arg_nodes[0] if arg_nodes else None
        path, host = _split_url(target or "")
        if path:
            walk.add_site(
                node,
                site_kind="http_client",
                rule_id="http.js.client",
                resolution="candidate",
                expression_text=_node_text(walk.source, node),
                payload={"method": method, "path": path, "host": host, "path_known": True},
                http_method=method,
                http_path=path,
                http_rev=path[::-1],
            )
            return True
        if arg0 is not None and arg0.type == "template_string" and _record_partial_url(walk, node, arg0, method):
            return True
        walk.add_site(
            node,
            site_kind="http_client",
            rule_id="http.js.client",
            resolution="unresolved",
            expression_text=_node_text(walk.source, node),
            payload={"reason": "dynamic url", "path_known": False},
        )
        return True
    path_value = values[0] if values else None
    path, host = _split_url(path_value or "")
    receiver_name = receiver.split(".")[-1]
    is_route = receiver_name in _ROUTE_RECEIVERS and path.startswith("/")
    is_client = receiver_name in _CLIENT_RECEIVERS and bool(path)
    if not is_route and not is_client:
        return False
    method = lower.upper()
    handler = ""
    if len(arg_nodes) >= 2 and arg_nodes[1].type == "identifier":
        handler = _node_text(walk.source, arg_nodes[1])
    kind = "http_route" if is_route else "http_client"
    rule = "http.cpp.method" if walk.lang == "cpp" else (
        "http.rust.route" if walk.lang == "rust" else ("http.js.route" if is_route else "http.js.client")
    )
    walk.add_site(
        node,
        site_kind=kind,
        rule_id=rule,
        resolution="candidate",
        expression_text=_node_text(walk.source, node),
        payload={"method": method, "path": path, "host": host, "handler": handler, "path_known": True},
        http_method=method,
        http_path=path,
        http_rev=path[::-1],
        handler_key=handler or None,
    )
    _walk_args(walk, arg_nodes)
    return True


def _walk_args(walk: _Walker, arg_nodes) -> None:
    for arg in arg_nodes:
        walk.visit(arg)


def _object_method(walk: _Walker, node) -> str | None:
    if node.type != "object":
        return None
    for child in _named(node):
        if child.type != "pair":
            continue
        key = child.child_by_field_name("key")
        value = child.child_by_field_name("value")
        if key is not None and _node_text(walk.source, key) == "method":
            literal = walk.eval_expr(value)
            if literal:
                return literal.upper()
    return None


def _split_url(value: str) -> tuple[str, str | None]:
    if not value:
        return "", None
    host = None
    path = value.split("?", 1)[0].split("#", 1)[0]
    if path.startswith("http://") or path.startswith("https://"):
        rest = path.split("://", 1)[1]
        slash = rest.find("/")
        if slash < 0:
            return "/", rest
        host = rest[:slash]
        path = rest[slash:]
    parts = []
    for seg in path.split("/"):
        if seg.startswith(":") or (seg.startswith("{") and seg.endswith("}")):
            parts.append("{}")
        else:
            parts.append(seg)
    path = "/".join(parts)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    if path and not path.startswith("/") and host is None:
        return "", None
    return path or "/", host


def _maybe_process(walk, node, lower, arg_nodes, values) -> bool:
    if lower in _SHELL_NAMES:
        walk.add_site(
            node,
            site_kind="process_spawn",
            rule_id="proc.js.spawn",
            resolution="unresolved",
            expression_text=_node_text(walk.source, node),
            payload={"reason": "shell string is not interpreted"},
        )
        return True
    if lower not in _SPAWN_NAMES:
        return False
    exe = values[0] if values else None
    if not exe:
        walk.add_site(
            node,
            site_kind="process_spawn",
            rule_id="proc.js.spawn",
            resolution="unresolved",
            expression_text=_node_text(walk.source, node),
            payload={"reason": "dynamic executable"},
        )
        return True
    args: list[str] = []
    if len(arg_nodes) >= 2:
        literals = _array_literals(walk, arg_nodes[1])
        if literals is None:
            walk.add_site(
                node,
                site_kind="process_spawn",
                rule_id="proc.js.spawn",
                resolution="unresolved",
                expression_text=_node_text(walk.source, node),
                payload={"reason": "dynamic arguments", "exe": Path(exe).name},
                exec_id=Path(exe).name,
            )
            return True
        args = literals
    exec_id = Path(exe).name
    walk.add_site(
        node,
        site_kind="process_spawn",
        rule_id="proc.js.spawn",
        resolution="candidate",
        expression_text=_node_text(walk.source, node),
        payload={"exe": exec_id, "args": args},
        exec_id=exec_id,
        exec_args_norm=" ".join(args),
    )
    return True


def _array_literals(walk: _Walker, node) -> list[str] | None:
    if node is None or node.type not in {"array", "array_expression"}:
        return None
    out = []
    for child in _named(node):
        value = walk.eval_expr(child)
        if value is None:
            return None
        out.append(value)
    return out


def _maybe_net(walk, node, lower, receiver, arg_nodes, values) -> bool:
    role = None
    if lower in _LISTEN_NAMES:
        role = "listen"
    elif lower in _CONNECT_NAMES:
        role = "connect"
    else:
        return False
    host, port, wildcard = _endpoint(walk, arg_nodes, values)
    if port is None:
        walk.add_site(
            node,
            site_kind="net_listen" if role == "listen" else "net_connect",
            rule_id="net.listen" if role == "listen" else "net.connect",
            resolution="unresolved",
            expression_text=_node_text(walk.source, node),
            payload={"role": role, "reason": "dynamic endpoint"},
            net_role=role,
        )
        return True
    kind = "net_listen" if role == "listen" else "net_connect"
    walk.add_site(
        node,
        site_kind=kind,
        rule_id="net.listen" if role == "listen" else "net.connect",
        resolution="candidate",
        expression_text=_node_text(walk.source, node),
        payload={"role": role, "host": host, "port": port, "wildcard": wildcard},
        net_host=host,
        net_port=port,
        net_role=role,
        net_wildcard=1 if wildcard else 0,
    )
    _ = receiver
    return True


def _endpoint(walk, arg_nodes, values) -> tuple[str | None, int | None, bool]:
    host = None
    port = None
    if arg_nodes and arg_nodes[0].type == "object":
        for child in _named(arg_nodes[0]):
            if child.type != "pair":
                continue
            key = child.child_by_field_name("key")
            value = child.child_by_field_name("value")
            if key is None:
                continue
            key_text = _node_text(walk.source, key)
            literal = walk.eval_expr(value)
            if key_text == "port" and literal and literal.isdigit():
                port = int(literal)
            if key_text == "host" and literal:
                host = literal
    elif values:
        first = values[0] or ""
        if first.isdigit():
            port = int(first)
            if len(values) > 1 and values[1]:
                host = values[1]
        elif ":" in first and first.rsplit(":", 1)[-1].isdigit():
            host, _, port_s = first.rpartition(":")
            port = int(port_s)
        elif len(values) > 1 and values[1] and str(values[1]).isdigit():
            host = first or None
            port = int(values[1])
    wildcard = host in {"0.0.0.0", "::", "[::]"}
    return host, port, wildcard


def _maybe_rpc_write(walk, node, name, receiver, values) -> bool:
    if name != "write" or "stdin" not in receiver:
        return False
    command = values[0] if values else None
    if not command or not _command_token(command):
        walk.add_site(
            node,
            site_kind="rpc_send",
            rule_id="rpc.send",
            resolution="unresolved",
            expression_text=_node_text(walk.source, node),
            payload={"reason": "dynamic stdin command"},
        )
        return True
    walk.add_site(
        node,
        site_kind="rpc_send",
        rule_id="rpc.send",
        resolution="candidate",
        expression_text=_node_text(walk.source, node),
        payload={"command": command},
        rpc_command=command,
    )
    return True


def _command_token(value: str) -> bool:
    if not value or len(value) > 64 or any(ch.isspace() for ch in value):
        return False
    return value[0].isalpha() or value.startswith("--")


def _handle_rust_fn(walk: _Walker, node) -> bool:
    name_node = node.child_by_field_name("name")
    name = _node_text(walk.source, name_node) if name_node is not None else ""
    params = _params_of(walk.source, node)
    body = node.child_by_field_name("body")
    symbol_id = walk.add_symbol(
        node,
        kind="function",
        name=name or "<anonymous>",
        params=params,
        signature=_norm(_node_text(walk.source, node).split("{", 1)[0]),
        role="decl_and_def" if body is not None else "declaration",
    )
    if name == "main" and body is not None:
        stem = Path(walk.path).stem
        walk.add_site(
            node,
            site_kind="process_entry",
            rule_id="proc.entry",
            resolution="resolved",
            expression_text=name,
            payload={"stem": stem},
            exec_id=None if stem.lower() in _GENERIC_STEMS else stem,
        )
    walk.scope.append(("function", name or symbol_id))
    walk.with_function(symbol_id, body)
    walk.scope.pop()
    return True


def _handle_rust_impl(walk: _Walker, node) -> bool:
    type_node = node.child_by_field_name("type")
    name = _node_text(walk.source, type_node) if type_node is not None else "<impl>"
    body = node.child_by_field_name("body")
    walk.scope.append(("impl", name))
    if body is not None:
        walk.visit(body)
    walk.scope.pop()
    return True


def _handle_rust_struct(walk: _Walker, node) -> bool:
    name_node = node.child_by_field_name("name")
    name = _node_text(walk.source, name_node) if name_node is not None else "<anonymous>"
    walk.add_symbol(
        node,
        kind="struct",
        name=name,
        params="",
        signature=_norm(_node_text(walk.source, node).split("{", 1)[0]),
        role="decl_and_def",
    )
    return False


def _handle_if_command(walk: _Walker, node) -> bool:
    condition = node.child_by_field_name("condition")
    command = _comparison_string(walk, condition)
    if command and _command_token(command):
        walk.add_site(
            node,
            site_kind="rpc_dispatch",
            rule_id="rpc.dispatch.arm",
            resolution="candidate",
            expression_text=_node_text(walk.source, condition or node),
            payload={"command": command},
            rpc_command=command,
        )
    return False


def _comparison_string(walk: _Walker, node) -> str | None:
    if node is None:
        return None
    if node.type == "parenthesized_expression" and node.named_child_count:
        return _comparison_string(walk, node.named_child(0))
    if node.type in {"binary_expression", "binary_expression"}:
        left = walk.eval_expr(node.child_by_field_name("left"))
        right = walk.eval_expr(node.child_by_field_name("right"))
        for value in (left, right):
            if value and not value.isdigit():
                return value
    return None


_HANDLERS = {
    ("cpp", "namespace_definition"): _handle_cpp_namespace,
    ("cpp", "class_specifier"): _handle_cpp_class,
    ("cpp", "struct_specifier"): _handle_cpp_class,
    ("cpp", "function_definition"): _handle_cpp_function,
    ("cpp", "declaration"): _handle_cpp_declaration,
    ("cpp", "field_declaration"): _handle_cpp_declaration,
    ("javascript", "function_declaration"): _handle_js_function,
    ("typescript", "function_declaration"): _handle_js_function,
    ("tsx", "function_declaration"): _handle_js_function,
    ("javascript", "arrow_function"): _handle_js_arrow,
    ("typescript", "arrow_function"): _handle_js_arrow,
    ("tsx", "arrow_function"): _handle_js_arrow,
    ("javascript", "class_declaration"): _handle_js_class,
    ("typescript", "class_declaration"): _handle_js_class,
    ("tsx", "class_declaration"): _handle_js_class,
    ("javascript", "import_statement"): _handle_import,
    ("typescript", "import_statement"): _handle_import,
    ("tsx", "import_statement"): _handle_import,
    ("*", "call_expression"): _handle_call,
    ("rust", "function_item"): _handle_rust_fn,
    ("rust", "impl_item"): _handle_rust_impl,
    ("rust", "struct_item"): _handle_rust_struct,
    ("*", "if_statement"): _handle_if_command,
    ("rust", "if_expression"): _handle_if_command,
}


def _handle_identifier(walk: _Walker, node) -> bool:
    """A name used as a value is a reference. The callee of a call is not."""
    parent = node.parent
    if parent is None:
        return False
    if parent.type == "call_expression" and parent.child_by_field_name("function") == node:
        return False
    interesting = False
    if parent.type in {"arguments", "argument_list", "argument"}:
        interesting = True
    value = parent.child_by_field_name("value") if parent.type in {"variable_declarator", "init_declarator"} else None
    right = parent.child_by_field_name("right") if parent.type == "assignment_expression" else None
    if value == node or right == node:
        interesting = True
    if not interesting:
        return False
    name = _node_text(walk.source, node)
    if name in walk.consts:
        return False
    walk.add_site(
        node,
        site_kind="reference",
        rule_id="lang.ref",
        resolution="unresolved",
        expression_text=name,
        payload={"name": name},
        callee_name=name,
        arg_count=None,
    )
    return False


_HANDLERS[("*", "identifier")] = _handle_identifier
