"""
process/core.py — GW-BASIC label compiler core
No CLI concerns here; all I/O decisions are made by the caller.
"""

import re
import os

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

def split_comment(line: str):
    """
    Splits a GW-BASIC line into (code, comment).

    Supports:
      ' comment
      REM comment   (only when REM is a standalone token)
    """

    stripped = line.lstrip()

    # ' style comment (anywhere)
    apos = line.find("'")
    if apos != -1:
        return line[:apos].rstrip(), line[apos:]

    # REM style comment (must be leading token)
    m = re.match(r"(?i)^\s*REM(\s+.*)?$", line)
    if m:
        return "", line  # whole line is comment

    m = re.match(r"(?i)^(.*?)(\s+REM\s+.*)$", line)
    if m:
        return m.group(1).rstrip(), m.group(2)

    return line, None

# =============================================================================
# DIAGNOSTICS
# =============================================================================

class Diagnostic:
    def __init__(self, file, line, col, code, message, source_line):
        self.file = file
        self.line = line
        self.col = col
        self.code = code
        self.message = message
        self.source_line = source_line

    def format(self):
        header = f"{self.file}:{self.line+1}:{self.col+1}: [{self.code}] {self.message}"
        caret = " " * self.col + "^"
        return f"{header}\n{self.source_line}\n{caret}"


# =============================================================================
# EXPANDER ONLY
# =============================================================================

class GWExpander:
    def __init__(self, step=DEFAULT_STEP, block_step=DEFAULT_BLOCK_STEP):
        self.step = step
        self.block_step = block_step

    # -----------------------------
    # PARSE
    # -----------------------------
    def parse(self, lines, filename):
        blocks = []
        current = {"label": None, "lines": []}
        line_no = 1

        for raw in lines:
            code, comment = split_comment(raw)

            m = re.match(r"^\s*([A-Za-z_]\w*)\s*:\s*(.*)$", code)

            if m:
                if current["label"] or current["lines"]:
                    blocks.append(current)

                current = {"label": m.group(1), "lines": []}

                rest = m.group(2).strip()
                if rest or comment:
                    current["lines"].append((line_no, 0, rest, comment))
            else:
                current["lines"].append((line_no, 0, code.strip(), comment))

            line_no += 1

        if current["label"] or current["lines"]:
            blocks.append(current)

        return blocks

    # -----------------------------
    # RESOLVE LABELS
    # -----------------------------
    def resolve(self, blocks, filename):
        label_to_block = {}
        diagnostics = []
        used_labels = set()

        for i, b in enumerate(blocks):
            if b["label"]:
                label_to_block[b["label"]] = i

        for b in blocks:
            new_lines = []

            for line_no, col, code, comment in b["lines"]:

                def repl(match):
                    keyword = match.group(1).upper()
                    label = match.group(2)

                    used_labels.add(label)
                    start_col = match.start(2)

                    if label not in label_to_block:
                        diagnostics.append(
                            Diagnostic(
                                file=filename,
                                line=line_no,
                                col=start_col,
                                code="unmatched-label",
                                message=f"Undefined label '{label}'",
                                source_line=code,
                            )
                        )
                        return f"{keyword} @{label}@"

                    return f"{keyword} @{label}@"

                new_code = re.sub(
                    r"\b(GOTO|GOSUB|THEN)\s+([A-Za-z_]\w*)",
                    repl,
                    code,
                    flags=re.IGNORECASE,
                )

                new_lines.append((line_no, col, new_code, comment))

            b["lines"] = new_lines

        return blocks, label_to_block, diagnostics, used_labels

    # -----------------------------
    # EMIT
    # -----------------------------
    def smart_upper(self, line):
        parts = re.split(r'(".*?")', line)
        for i in range(len(parts)):
            if not parts[i].startswith('"'):
                parts[i] = parts[i].upper()
        return "".join(parts)

    def compute_block_starts(self, blocks):
        block_starts = {}
        line_no = self.step

        for i, b in enumerate(blocks):
            if b["label"]:
                if line_no % self.block_step != 0:
                    line_no = (line_no // self.block_step + 1) * self.block_step
                block_starts[i] = line_no
                line_no += self.step
            else:
                block_starts[i] = line_no

            for line in b["lines"]:
                if line[2].strip():
                    line_no += self.step

        return block_starts

    def emit(self, blocks, label_map, used_labels):
        block_starts = self.compute_block_starts(blocks)

        label_to_line = {
            k: block_starts[v]
            for k, v in label_map.items()
            if k in used_labels
        }

        out = []
        line_no = self.step

        for i, b in enumerate(blocks):
            if b["label"]:
                line_no = block_starts[i]
                out.append(f"{line_no} '[ {b['label'].upper()} ]")
                line_no += self.step

            for ln, col, code, comment in b["lines"]:
                if not code and not comment:
                    out.append("")
                    continue

                # --- normalize code aggressively ---
                code = code.strip()

                def fix(m):
                    label = m.group(2)
                    target = label_to_line.get(label)
                    return f"{m.group(1)} {target if target is not None else 0} ' {label}"

                code = re.sub(
                    r"\b(GOTO|GOSUB|THEN)\s+@([A-Za-z_]\w*)@",
                    fix,
                    code,
                )

                code = self.smart_upper(code).strip()

                # --- normalize comment ---
                if comment:
                    comment = comment.lstrip()
                    if len(code):
                        out.append(f"{line_no} {code} {comment}")
                    else:
                        out.append(f"{line_no} {comment}")
                else:
                    out.append(f"{line_no} {code}")

                line_no += self.step

        return out

    # -----------------------------
    # PUBLIC API
    # -----------------------------
    def run(self, src_lines, filename):
        blocks = self.parse(src_lines, filename)
        blocks, label_map, diags, used = self.resolve(blocks, filename)
        out = self.emit(blocks, label_map, used)
        return out, diags