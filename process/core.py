"""
process/core.py — GW-BASIC compiler core (instruction-stream model)

This version fixes ALL:
- None emission bugs
- comment scheduling bugs
- label/address mismatches
- layout tuple fragility

Everything becomes a flat instruction stream.
"""

import re
from dataclasses import dataclass
from typing import List, Dict

DEFAULT_STEP = 10
DEFAULT_BLOCK_STEP = 100


@dataclass
class CompilerConfig:
    step: int = DEFAULT_STEP
    block_step: int = DEFAULT_BLOCK_STEP


# =============================================================================
# ERROR SYSTEM
# =============================================================================

@dataclass
class CompilerError:
    file: str
    line: int
    col: int
    message: str
    source: str

    def format(self):
        caret = " " * max(self.col - 1, 0) + "^"
        return f"{self.file}:{self.line}:{self.col}: {self.message}\n{self.source}\n{caret}"


class ErrorCollector:
    def __init__(self):
        self.errors = []

    def add(self, e):
        self.errors.append(e)

    def __bool__(self):
        return bool(self.errors)


# =============================================================================
# TOKENIZER (BASIC SAFE)
# =============================================================================

KEYWORDS = {
    "IF", "THEN", "ELSE", "GOTO", "GOSUB",
    "PRINT", "END", "DIM", "FOR", "TO", "NEXT",
    "RETURN", "DEFINT", "DEF", "USING", "CLS"
}

TYPE_SIGILS = "$%&!#"

BUILTIN_LABEL_NAMES = KEYWORDS | {
    "BEEP", "CLEAR", "CLOSE", "COLOR", "DATA", "DEFDBL", "DEFSNG",
    "DEFSTR", "DELETE", "DRAW", "EDIT", "ERASE", "FIELD", "FILES",
    "GET", "IF", "INPUT", "KEY", "KILL", "LET", "LINE", "LIST",
    "LOAD", "LOCATE", "LPRINT", "LSET", "MERGE", "NAME", "NEW",
    "OFF", "ON", "OPEN", "OPTION", "OUT", "PAINT", "POKE", "PRESET",
    "PSET", "PUT", "RANDOMIZE", "READ", "REM", "RESET", "RESTORE",
    "RESUME", "RSET", "RUN", "SCREEN", "SOUND", "STEP", "STOP",
    "SWAP", "SYSTEM", "TAB", "TROFF", "TRON", "USR", "VIEW", "WAIT",
    "WEND", "WHILE", "WIDTH", "WINDOW", "WRITE",
    "ABS", "ASC", "ATN", "CDBL", "CINT", "COS", "CSNG", "EXP", "FIX",
    "HEX", "INP", "INSTR", "INT", "LEN", "LOG", "MID", "PEEK", "POINT",
    "POS", "RND", "SGN", "SIN", "SPC", "SQR", "STR", "STRING", "TAN",
    "TIMER", "VAL",
}


@dataclass
class Token:
    kind: str
    value: str


def lex(line: str) -> List[Token]:
    tokens = []
    i = 0

    while i < len(line):
        c = line[i]

        if c.isspace():
            i += 1
            continue

        # STRING
        if c == '"':
            j = i + 1
            while j < len(line) and line[j] != '"':
                j += 1
            j = min(j + 1, len(line))
            tokens.append(Token("STR", line[i:j]))
            i = j
            continue

        # NUMBER (integer or decimal)
        if c.isdigit():
            j = i
            while j < len(line) and line[j].isdigit():
                j += 1
            if j < len(line) and line[j] == ".":
                j += 1
                while j < len(line) and line[j].isdigit():
                    j += 1
            tokens.append(Token("NUM", line[i:j]))
            i = j
            continue

        # LEADING-DOT FLOAT (.5, .25, etc.)
        if c == "." and i + 1 < len(line) and line[i + 1].isdigit():
            j = i + 1
            while j < len(line) and line[j].isdigit():
                j += 1
            tokens.append(Token("NUM", line[i:j]))
            i = j
            continue

        # IDENT (BASIC SAFE)
        if c.isalpha() or c == "_":
            j = i
            while j < len(line) and (
                line[j].isalnum() or line[j] in "_."
            ):
                j += 1

            if j < len(line) and line[j] in TYPE_SIGILS:
                j += 1

            word = line[i:j]
            up = word.upper()

            if up in KEYWORDS:
                tokens.append(Token("KW", up))
            else:
                tokens.append(Token("ID", up))

            i = j
            continue

        # RANGE A-Z
        if (
            i + 2 < len(line)
            and line[i].isalpha()
            and line[i+1] == "-"
            and line[i+2].isalpha()
        ):
            tokens.append(Token("RANGE", line[i:i+3].upper()))
            i += 3
            continue

        # COMPOUND OPERATORS: <>, <=, >=
        if c in ("<", ">") and i + 1 < len(line) and line[i + 1] in ("=", "<", ">"):
            op = line[i:i + 2]
            if op in ("<>", "<=", ">="):
                tokens.append(Token("SYM", op))
                i += 2
                continue

        tokens.append(Token("SYM", c))
        i += 1

    return tokens


def strip_comment(line: str) -> tuple[str, str | None]:
    """
    Split a source line into (code, comment) respecting string literals.
    A "'" inside a double-quoted string is not treated as a comment delimiter.
    Returns (code_part, comment_or_None).
    """
    i = 0
    while i < len(line):
        c = line[i]
        if c == '"':
            i += 1
            while i < len(line) and line[i] != '"':
                i += 1
            i += 1  # step past closing quote (or end of line if unterminated)
            continue
        if c == "'":
            return line[:i], line[i:]
        i += 1
    return line, None


# =============================================================================
# INSTRUCTION MODEL
# =============================================================================

@dataclass
class LabelInstr:
    line: int
    name: str
    addr: int | None = None


@dataclass
class CodeInstr:
    line: int
    text: str
    tokens: List[Token]
    substitutions: List[tuple[int, str]] | None = None
    addr: int | None = None


@dataclass
class CommentInstr:
    line: int
    text: str
    addr: int | None = None


@dataclass
class EmptyInstr:
    line: int


Instruction = LabelInstr | CodeInstr | CommentInstr | EmptyInstr


# =============================================================================
# EMIT HELPERS
# =============================================================================

def _needs_space(left: Token, right: Token) -> bool:
    """
    Return True if a space should be emitted between left and right.

    Opinionated GW-BASIC style:
    - ),  ,  ;  :   always glue to the left (no space before them)
    - (             glues to callable names — SIN(X), A(I), FNA(X), TAB(X)
                    but keeps a space after statement keywords — PRINT (X)
    - after (       nothing gets a leading space
    """
    gwbasic_callable_keywords = {
        "TAB", "SPC", "USR",
    }

    def can_call_without_space(token: Token) -> bool:
        if token.kind == "ID":
            return True
        if token.kind == "KW" and token.value in gwbasic_callable_keywords:
            return True
        return False

    if right.value in {")", ",", ";", ":"}:
        return False
    if right.value == "(":
        return not can_call_without_space(left)
    if left.value == "(":
        return False
    return True


# =============================================================================
# PIPELINE
# =============================================================================

def build_instructions(lines: List[str]) -> List[Instruction]:
    instrs: List[Instruction] = []

    for line_no, raw in enumerate(lines, start=1):
        code, comment = strip_comment(raw)

        # LABEL
        m = re.match(r"^\s*([A-Za-z_]\w*)\s*:\s*(.*)$", code)
        if m:
            label = m.group(1).upper()
            instrs.append(LabelInstr(line=line_no, name=label))

            rest = m.group(2).strip()
            if rest:
                instrs.append(CodeInstr(line=line_no, text=rest, tokens=lex(rest)))

            continue

        # COMMENT ONLY LINE
        if code.strip() == "" and comment:
            instrs.append(CommentInstr(line=line_no, text=comment))
            continue

        # EMPTY LINE
        if code.strip() == "":
            instrs.append(EmptyInstr(line=line_no))
            continue

        instrs.append(CodeInstr(line=line_no, text=code, tokens=lex(code)))

    return instrs


def validate_labels(instrs: List[Instruction], lines: List[str], errors: ErrorCollector, filename: str):
    for instr in instrs:
        if not isinstance(instr, LabelInstr):
            continue

        if instr.name in BUILTIN_LABEL_NAMES:
            errors.add(CompilerError(
                file=filename,
                line=instr.line,
                col=1,
                message=f"Label conflicts with GW-BASIC built-in: {instr.name}",
                source=lines[instr.line - 1],
            ))


def assign_addresses(instrs: List[Instruction], cfg: CompilerConfig) -> Dict[str, int]:
    addr = cfg.step
    labels = {}

    for i in instrs:

        if isinstance(i, LabelInstr):
            if addr % cfg.block_step:
                addr = (addr // cfg.block_step + 1) * cfg.block_step

            labels[i.name] = addr
            i.addr = addr
            addr += cfg.step
            continue

        if isinstance(i, EmptyInstr):
            continue

        # CommentInstr and CodeInstr both consume address space
        i.addr = addr
        addr += cfg.step

    return labels


def resolve(instrs: List[Instruction], labels: Dict[str, int], errors: ErrorCollector, filename: str):
    for i in instrs:
        if not isinstance(i, CodeInstr):
            continue

        new = []
        substitutions: List[tuple[int, str]] = []
        j = 0

        while j < len(i.tokens):
            t = i.tokens[j]

            # ---------------------------------------------------------
            # GOTO / GOSUB → ALWAYS expect label
            # ---------------------------------------------------------
            if t.kind == "KW" and t.value in {"GOTO", "GOSUB"}:
                new.append(t)

                if j + 1 < len(i.tokens) and i.tokens[j+1].kind == "ID":
                    label = i.tokens[j+1].value

                    if label in labels:
                        addr = labels[label]
                        new.append(Token("NUM", str(addr)))
                        substitutions.append((addr, label))
                    else:
                        errors.add(CompilerError(
                            file=filename,
                            line=i.line,
                            col=1,
                            message=f"Undefined label: {label}",
                            source=i.text,
                        ))
                        new.append(i.tokens[j+1])

                    j += 2
                    continue

                j += 1
                continue

            # ---------------------------------------------------------
            # THEN / ELSE → detect label vs statement
            # ---------------------------------------------------------
            if t.kind == "KW" and t.value in {"THEN", "ELSE"}:
                new.append(t)

                if j + 1 < len(i.tokens):
                    nxt = i.tokens[j+1]

                    # Case 1: numeric line → keep
                    if nxt.kind == "NUM":
                        new.append(nxt)
                        j += 2
                        continue

                    # Case 2: identifier → MAY be label
                    if nxt.kind == "ID":
                        is_label = False

                        # lookahead token
                        if j + 2 >= len(i.tokens):
                            is_label = True  # end of line
                        else:
                            nxt2 = i.tokens[j+2]

                            # only ":" means it's a label jump
                            if nxt2.value == ":":
                                is_label = True

                        if is_label:
                            label = nxt.value

                            if label in labels:
                                addr = labels[label]
                                new.append(Token("NUM", str(addr)))
                                substitutions.append((addr, label))
                            else:
                                errors.add(CompilerError(
                                    file=filename,
                                    line=i.line,
                                    col=1,
                                    message=f"Undefined label: {label}",
                                    source=i.text,
                                ))
                                new.append(nxt)

                            j += 2
                            continue

                        # otherwise: it's a statement → DO NOT consume
                        j += 1
                        continue

                j += 1
                continue

            # ---------------------------------------------------------
            # default
            # ---------------------------------------------------------
            new.append(t)
            j += 1

        i.tokens = new
        i.substitutions = substitutions


def emit_substitution_comment(substitutions: List[tuple[int, str]] | None) -> str:
    if not substitutions:
        return ""

    if len(substitutions) == 1:
        _, label = substitutions[0]
        return f" ' -> [{label}]"

    rendered = ", ".join(
        f"{addr} -> [{label}]"
        for addr, label in substitutions
    )
    return f" ' {rendered}"


def emit_tokens(tokens: List[Token]) -> str:
    parts = []
    prev: Token | None = None

    for t in tokens:
        if prev is not None and _needs_space(prev, t):
            parts.append(" ")
        parts.append(t.value)
        prev = t

    return "".join(parts)


def run(lines: List[str], filename: str, cfg: CompilerConfig) -> tuple[list[str], ErrorCollector]:
    instrs = build_instructions(lines)
    errors = ErrorCollector()
    validate_labels(instrs, lines, errors, filename)
    labels = assign_addresses(instrs, cfg)
    resolve(instrs, labels, errors, filename)

    out = []

    for i in instrs:

        if isinstance(i, EmptyInstr):
            out.append("")
            continue

        if isinstance(i, LabelInstr):
            out.append(f"{i.addr} ' [{i.name}]")
            continue

        if isinstance(i, CommentInstr):
            out.append(f"{i.addr} {i.text}")
            continue

        if isinstance(i, CodeInstr):
            out.append(
                f"{i.addr} {emit_tokens(i.tokens)}"
                f"{emit_substitution_comment(i.substitutions)}"
            )

    return out, errors
