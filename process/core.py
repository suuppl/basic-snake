"""
process/core.py — GW-BASIC label compiler core
"""

import re
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple


DEFAULT_STEP = 10
DEFAULT_BLOCK_STEP = 100


# =============================================================================
# FILE HELPERS
# =============================================================================

def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


def write(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def dos_name(path):
    dir_, base = os.path.split(path)
    return os.path.join(dir_, base.upper()) if dir_ else base.upper()


def find_existing_ci(path):
    dir_ = os.path.dirname(path) or "."
    target = os.path.basename(path).upper()

    try:
        entries = os.listdir(dir_)
    except FileNotFoundError:
        return None

    for e in entries:
        if e.upper() == target:
            return os.path.join(dir_, e)

    return None


# =============================================================================
# ERROR SYSTEM
# =============================================================================

class CompilerError(Exception):
    def __init__(self, file, line, col, message, line_text=None):
        self.file = file
        self.line = line
        self.col = col
        self.message = message
        self.line_text = line_text

    def format(self):
        header = f"{self.file}:{self.line}:{self.col}: {self.message}"

        if not self.line_text:
            return header

        caret = " " * max(self.col - 1, 0) + "^"
        return f"{header}\n{self.line_text}\n{caret}"

    def __str__(self):
        return self.format()


class ErrorCollector:
    def __init__(self):
        self.errors: List[CompilerError] = []

    def add(self, e: CompilerError):
        self.errors.append(e)

    def __bool__(self):
        return bool(self.errors)

    def __str__(self):
        return "\n\n".join(e.format() for e in self.errors)


# =============================================================================
# LEXER (CASE INSENSITIVE KEYWORDS)
# =============================================================================

KEYWORDS = {k.upper() for k in {
    "IF", "THEN", "ELSE", "GOTO", "GOSUB", "RETURN", "END"
}}


@dataclass
class Token:
    type: str
    value: str
    file: str
    line: int
    col: int


def lex(line: str, file: str, line_no: int) -> List[Token]:
    tokens = []
    i = 0
    n = len(line)

    while i < n:
        c = line[i]

        if c.isspace():
            i += 1
            continue

        col = i + 1

        # STRING
        if c == '"':
            j = i + 1
            while j < n and line[j] != '"':
                j += 1
            j = min(j + 1, n)
            tokens.append(Token("STRING", line[i:j], file, line_no, col))
            i = j
            continue

        # IDENT / KEYWORD
        if c.isalpha() or c == "_":
            j = i
            while j < n and (line[j].isalnum() or line[j] == "_"):
                j += 1

            word = line[i:j]
            upper = word.upper()

            if upper in KEYWORDS:
                tokens.append(Token("KW", upper, file, line_no, col))
            else:
                tokens.append(Token("ID", word, file, line_no, col))

            i = j
            continue

        # SYMBOL
        tokens.append(Token("SYM", c, file, line_no, col))
        i += 1

    return tokens


# =============================================================================
# AST
# =============================================================================

@dataclass
class Node:
    pass


@dataclass
class Statement(Node):
    text: str


@dataclass
class Goto(Node):
    label: str
    token: Token


@dataclass
class Gosub(Node):
    label: str
    token: Token


@dataclass
class If(Node):
    cond: str
    then_node: Node
    else_node: Optional[Node]
    token: Token


# =============================================================================
# PARSER
# =============================================================================

def parse(tokens: List[Token], file: str, line_text: str, errors: ErrorCollector) -> Node:
    if not tokens:
        return Statement("")

    # IF
    if tokens[0].type == "KW" and tokens[0].value == "IF":

        then_i = None
        else_i = None

        for i, t in enumerate(tokens):
            if t.type == "KW" and t.value == "THEN":
                then_i = i
            elif t.type == "KW" and t.value == "ELSE":
                else_i = i

        if then_i is None:
            t = tokens[0]
            errors.add(CompilerError(
                t.file, t.line, t.col,
                "IF missing THEN",
                line_text=line_text
            ))
            return Statement("")

        cond = " ".join(t.value for t in tokens[1:then_i])

        then_tokens = tokens[then_i + 1: else_i if else_i else len(tokens)]
        else_tokens = tokens[else_i + 1:] if else_i else []

        def wrap(ts):
            if len(ts) == 1 and ts[0].type == "ID":
                return [
                    Token("KW", "GOTO", ts[0].file, ts[0].line, ts[0].col),
                    ts[0]
                ]
            return ts

        then_tokens = wrap(then_tokens)
        else_tokens = wrap(else_tokens) if else_tokens else []

        return If(
            cond=cond,
            then_node=parse(then_tokens, file, line_text, errors),
            else_node=parse(else_tokens, file, line_text, errors) if else_tokens else None,
            token=tokens[0],
        )

    # GOTO / GOSUB
    if len(tokens) >= 2 and tokens[0].type == "KW":

        if tokens[0].value == "GOTO":
            return Goto(tokens[1].value.upper(), tokens[1])

        if tokens[0].value == "GOSUB":
            return Gosub(tokens[1].value.upper(), tokens[1])

    return Statement(" ".join(t.value for t in tokens))


# =============================================================================
# COMMENT SPLIT
# =============================================================================

def split_comment(line: str):
    apos = line.find("'")
    if apos != -1:
        return line[:apos].rstrip(), line[apos:]

    m = re.match(r"(?i)^(.*?)(\s+REM\s+.*)$", line)
    if m:
        return m.group(1).rstrip(), m.group(2)

    return line, None


# =============================================================================
# COMPILER
# =============================================================================

class Compiler:
    def __init__(self, step=DEFAULT_STEP, block_step=DEFAULT_BLOCK_STEP):
        self.step = step
        self.block_step = block_step

    # ------------------------------------------------------------
    # SPLIT BLOCKS (LABELS CASE INSENSITIVE)
    # ------------------------------------------------------------
    def split_blocks(self, lines):
        blocks = []
        current = {"label": None, "lines": []}

        for raw in lines:
            code, comment = split_comment(raw)

            m = re.match(r"^\s*([A-Za-z_]\w*)\s*:\s*(.*)$", code)

            if m:
                if current["label"] or current["lines"]:
                    blocks.append(current)

                current = {"label": m.group(1).upper(), "lines": []}

                rest = m.group(2).strip()
                if rest or comment:
                    current["lines"].append((rest, comment))
                continue

            if code.strip() == "":
                current["lines"].append((None, comment))
            else:
                current["lines"].append((code.strip(), comment))

        if current["label"] or current["lines"]:
            blocks.append(current)

        return blocks

    # ------------------------------------------------------------
    # BUILD AST
    # ------------------------------------------------------------
    def build_ast(self, blocks, filename):
        errors = ErrorCollector()

        for b in blocks:
            ast = []

            for li, (code, comment) in enumerate(b["lines"]):

                if code is None:
                    ast.append((None, comment, li, None))
                    continue

                tokens = lex(code, filename, li + 1)
                node = parse(tokens, filename, code, errors)

                ast.append((node, comment, li, code))

            b["ast"] = ast

        return blocks, errors

    # ------------------------------------------------------------
    # ADDRESS ASSIGNMENT
    # ------------------------------------------------------------
    def assign_addresses(self, blocks):
        addr = self.step
        label_to_addr = {}
        layout = []

        for bi, b in enumerate(blocks):

            if b["label"]:
                if addr % self.block_step != 0:
                    addr = (addr // self.block_step + 1) * self.block_step

                label_to_addr[b["label"]] = addr
                layout.append((bi, None, addr))
                addr += self.step

            for li, (node, _, _, _) in enumerate(b["ast"]):

                if node is None:
                    layout.append((bi, li, None))
                    continue

                layout.append((bi, li, addr))
                addr += self.step

        return label_to_addr, layout

    # ------------------------------------------------------------
    # EMIT NODE (CASE INSENSITIVE LABELS)
    # ------------------------------------------------------------
    def emit_node(self, node, labels, ann, errors, source_line=None):
        if isinstance(node, Statement):
            return node.text

        if isinstance(node, Goto):
            label = node.label.upper()

            if label not in labels:
                errors.add(CompilerError(
                    node.token.file,
                    node.token.line,
                    node.token.col,
                    f"undefined label '{node.label}'",
                    line_text=source_line
                ))
                ann.append(f"0 -> [{node.label}]")
                return "GOTO 0"

            ann.append(f"{labels[label]} -> [{label}]")
            return f"GOTO {labels[label]}"

        if isinstance(node, Gosub):
            label = node.label.upper()

            if label not in labels:
                errors.add(CompilerError(
                    node.token.file,
                    node.token.line,
                    node.token.col,
                    f"undefined label '{node.label}'",
                    line_text=source_line
                ))
                ann.append(f"0 -> [{node.label}]")
                return "GOSUB 0"

            ann.append(f"{labels[label]} -> [{label}]")
            return f"GOSUB {labels[label]}"

        if isinstance(node, If):
            then_part = self.emit_node(node.then_node, labels, ann, errors, source_line)
            else_part = (
                self.emit_node(node.else_node, labels, ann, errors, source_line)
                if node.else_node else None
            )

            if else_part:
                return f"IF {node.cond} THEN {then_part} ELSE {else_part}"
            return f"IF {node.cond} THEN {then_part}"

        return ""

    # ------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------
    def run(self, src_lines, filename):
        blocks = self.split_blocks(src_lines)
        blocks, errors = self.build_ast(blocks, filename)

        labels, layout = self.assign_addresses(blocks)

        out = []

        for bi, li, addr in layout:
            block = blocks[bi]

            if li is None:
                out.append(f"{addr} '[ {block['label']} ]")
                continue

            node, comment, _, source_line = block["ast"][li]

            if node is None:
                out.append("")
                continue

            ann = []
            code = self.emit_node(node, labels, ann, errors, source_line).upper()

            annotation = ""
            if ann:
                annotation = " ' " + ", ".join(ann)

            if comment:
                out.append(f"{addr} {code}{annotation} {comment}")
            else:
                out.append(f"{addr} {code}{annotation}")

        return out, errors