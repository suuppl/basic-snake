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
from typing import List, Optional, Dict

DEFAULT_STEP = 10
DEFAULT_BLOCK_STEP = 100




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

        # NUMBER
        if c.isdigit():
            j = i
            while j < len(line) and line[j].isdigit():
                j += 1
            tokens.append(Token("NUM", line[i:j]))
            i = j
            continue

        # IDENT (BASIC SAFE)
        if c.isalpha() or c == "_":
            j = i
            while j < len(line) and (
                line[j].isalnum() or line[j] in "_$."
            ):
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

        tokens.append(Token("SYM", c))
        i += 1

    return tokens


# =============================================================================
# INSTRUCTION MODEL (NEW CORE)
# =============================================================================

@dataclass
class Instruction:
    kind: str        # CODE | COMMENT | LABEL | EMPTY
    addr: Optional[int]
    text: str
    line: int
    tokens: Optional[List[Token]] = None


# =============================================================================
# COMPILER
# =============================================================================

class Compiler:
    def __init__(self, step=DEFAULT_STEP, block_step=DEFAULT_BLOCK_STEP):
        self.step = step
        self.block_step = block_step

    # ------------------------------------------------------------
    # PARSE INTO FLAT INSTRUCTION STREAM
    # ------------------------------------------------------------
    def build_instructions(self, lines: List[str]) -> List[Instruction]:
        instrs = []

        for line_no, raw in enumerate(lines, start=1):
            code = raw
            comment = None

            if "'" in raw:
                i = raw.index("'")
                code = raw[:i]
                comment = raw[i:]

            # LABEL
            m = re.match(r"^\s*([A-Za-z_]\w*)\s*:\s*(.*)$", code)
            if m:
                label = m.group(1).upper()

                instrs.append(Instruction(
                    kind="LABEL",
                    addr=None,
                    text=label,
                    line=line_no
                ))

                rest = m.group(2).strip()
                if rest:
                    instrs.append(Instruction(
                        kind="CODE",
                        addr=None,
                        text=rest,
                        tokens=lex(rest),
                        line=line_no
                    ))

                continue

            # COMMENT ONLY LINE
            if code.strip() == "" and comment:
                instrs.append(Instruction(
                    kind="COMMENT",
                    addr=None,
                    text=comment,
                    line=line_no
                ))
                continue

            # EMPTY LINE
            if code.strip() == "":
                instrs.append(Instruction(
                    kind="EMPTY",
                    addr=None,
                    text="",
                    line=line_no
                ))
                continue

            instrs.append(Instruction(
                kind="CODE",
                addr=None,
                text=code,
                tokens=lex(code),
                line=line_no
            ))

        return instrs

    # ------------------------------------------------------------
    # ADDRESS ASSIGNMENT (SIMPLE + SAFE)
    # ------------------------------------------------------------
    def assign_addresses(self, instrs: List[Instruction]):
        addr = self.step
        labels = {}

        for i in instrs:

            if i.kind == "LABEL":
                if addr % self.block_step:
                    addr = (addr // self.block_step + 1) * self.block_step

                labels[i.text] = addr
                i.addr = addr
                addr += self.step
                continue

            if i.kind == "EMPTY":
                i.addr = None
                continue

            # COMMENT + CODE both consume space
            i.addr = addr
            addr += self.step

        return labels

    # ------------------------------------------------------------
    # RESOLVE LABELS IN TOKENS
    # ------------------------------------------------------------
    def resolve(self, instrs: List[Instruction], labels: Dict[str, int], errors: ErrorCollector, filename: str):
        for i in instrs:
            if i.kind != "CODE":
                continue

            if not i.tokens:
                i.tokens = lex(i.text)

            new = []
            j = 0

            while j < len(i.tokens):
                t = i.tokens[j]

                if t.kind == "KW" and t.value in {"GOTO", "GOSUB", "THEN", "ELSE"}:
                    new.append(t)

                    if j + 1 < len(i.tokens) and i.tokens[j+1].kind == "ID":
                        label = i.tokens[j+1].value
                        if label in labels:
                            new.append(Token("NUM", str(labels[label])))
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

                new.append(t)
                j += 1

            i.tokens = new

    # ------------------------------------------------------------
    # EMITTER
    # ------------------------------------------------------------
    def emit_tokens(self, tokens: List[Token]) -> str:
        out = []

        def space():
            if out and out[-1] not in {" ", "(", ""}:
                out.append(" ")

        for t in tokens:
            if t.kind == "STR":
                space()
                out.append(t.value)
                continue

            v = t.value

            if v in {")", ",", ";"}:
                out.append(v)
                continue

            if v == "(":
                out.append(v)
                continue

            space()
            out.append(v)

        return "".join(out).strip()

    # ------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------
    def run(self, lines, filename):
        instrs = self.build_instructions(lines)
        labels = self.assign_addresses(instrs)
        errors = ErrorCollector()
        self.resolve(instrs, labels, errors, filename)

        out = []

        for i in instrs:

            if i.kind == "EMPTY":
                out.append("")
                continue

            if i.kind == "LABEL":
                out.append(f"{i.addr} ' [{i.text}]")
                continue

            if i.kind == "COMMENT":
                out.append(f"{i.addr} {i.text}")
                continue

            if i.kind == "CODE":
                code = self.emit_tokens(i.tokens or [])
                out.append(f"{i.addr} {code}")

        return out, ErrorCollector()