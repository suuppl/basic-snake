"""
process/core.py — GW-BASIC label compiler/decompiler core

No CLI concerns here; all I/O decisions are made by the caller.
"""

import re
import os

DEFAULT_STEP = 10
DEFAULT_BLOCK_STEP = 100


# =============================================================================
# SHARED FILE HELPERS
# =============================================================================

def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


def write(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def dos_name(path):
    """Return path with the basename uppercased (DOS style)."""
    dir_, base = os.path.split(path)
    return os.path.join(dir_, base.upper()) if dir_ else base.upper()


def find_existing_ci(path):
    """
    Case-insensitive search for path in its directory.
    Returns the actual on-disk path if a match is found, else None.
    """
    dir_ = os.path.dirname(path) or "."
    target = os.path.basename(path).upper()
    try:
        entries = os.listdir(dir_)
    except FileNotFoundError:
        return None
    for entry in entries:
        if entry.upper() == target:
            return os.path.join(dir_, entry)
    return None


# =============================================================================
# EXPANDER  (.pbas -> .bas)
# =============================================================================

class GWExpander:
    def __init__(self, step=DEFAULT_STEP, block_step=DEFAULT_BLOCK_STEP):
        self.step = step
        self.block_step = block_step

    # -----------------------------
    # PASS 1: PARSE + LABELS
    # -----------------------------
    def parse(self, lines):
        """
        Converts source into structured blocks:
        [
            {"label": "INIT", "lines": [...]},
            {"label": "MAIN", "lines": [...]}
        ]
        """
        blocks = []
        current = {"label": None, "lines": []}

        for line in lines:
            m = re.match(r"^\s*([A-Za-z_]\w*)\s*:\s*(.*)$", line)
            if m:
                if current["label"] is not None or current["lines"]:
                    blocks.append(current)
                current = {"label": m.group(1), "lines": []}
                rest = m.group(2).strip()
                if rest:
                    current["lines"].append(rest)
            else:
                current["lines"].append(line)

        if current["label"] is not None or current["lines"]:
            blocks.append(current)

        return blocks

    # -----------------------------
    # PASS 2: RESOLVE LABELS
    # -----------------------------
    def resolve(self, blocks):
        label_to_block = {}
        for i, b in enumerate(blocks):
            if b["label"]:
                label_to_block[b["label"]] = i

        for b in blocks:
            new_lines = []
            for line in b["lines"]:
                def repl(match):
                    keyword = match.group(1).upper()
                    label = match.group(2)
                    if label not in label_to_block:
                        raise ValueError(f"Undefined label: {label}")
                    return f"{keyword} @{label}@"

                line = re.sub(
                    r"\b(GOTO|GOSUB)\s+([A-Za-z_]\w*)",
                    repl,
                    line,
                    flags=re.IGNORECASE,
                )
                new_lines.append(line)
            b["lines"] = new_lines

        return blocks, label_to_block

    # -----------------------------
    # PASS 3: NUMBER + EMIT
    # -----------------------------
    def smart_upper(self, line):
        parts = re.split(r'(".*?")', line)
        for i in range(len(parts)):
            if not parts[i].startswith('"'):
                parts[i] = parts[i].upper()
        return "".join(parts)

    def compute_block_starts(self, blocks):
        """
        Pre-scan: compute the actual starting line number for each block,
        snapping labelled blocks to the next block_step boundary.
        """
        block_starts = {}
        line_no = self.step

        for i, b in enumerate(blocks):
            if b["label"]:
                if line_no % self.block_step != 0:
                    line_no = (line_no // self.block_step + 1) * self.block_step
                block_starts[i] = line_no
                line_no += self.step  # label comment line
            else:
                block_starts[i] = line_no

            for line in b["lines"]:
                if line.strip():
                    line_no += self.step

        return block_starts

    def emit(self, blocks, label_map):
        block_starts = self.compute_block_starts(blocks)
        label_to_line = {label: block_starts[idx] for label, idx in label_map.items()}

        output = []
        line_no = self.step

        for i, b in enumerate(blocks):
            if b["label"]:
                line_no = block_starts[i]
                output.append(f"{line_no} '[ {b['label'].upper()} ]")
                line_no += self.step

            for line in b["lines"]:
                if not line.strip():
                    output.append("")
                    continue

                def fix(match, _lmap=label_to_line):
                    label = match.group(2)
                    return f"{match.group(1)} {_lmap[label]} ' >> [ {label} ]"

                line = re.sub(r"\b(GOTO|GOSUB)\s+@([A-Za-z_]\w*)@", fix, line)
                line = self.smart_upper(line)
                output.append(f"{line_no} {line}")
                line_no += self.step

        return output

    def run(self, src_lines):
        """Parse, resolve and emit. Returns output lines."""
        blocks = self.parse(src_lines)
        blocks, label_map = self.resolve(blocks)
        return self.emit(blocks, label_map)


# =============================================================================
# COLLAPSER  (.bas -> .pbas)
# =============================================================================

class GWCollapser:
    # -----------------------------
    # PASS 1: PARSE NUMBERED LINES
    # -----------------------------
    def parse(self, raw_lines):
        """
        Returns a list of dicts:
          {"lineno": int,  "content": str}  for numbered lines
          {"lineno": None, "content": ""}   for blank spacers
        """
        parsed = []
        for raw in raw_lines:
            if not raw.strip():
                parsed.append({"lineno": None, "content": ""})
                continue
            m = re.match(r"^(\d+)\s*(.*)", raw)
            if m:
                parsed.append({"lineno": int(m.group(1)), "content": m.group(2)})
            else:
                parsed.append({"lineno": None, "content": raw})
        return parsed

    # -----------------------------
    # PASS 2: BUILD LABEL MAP
    # -----------------------------
    def build_label_map(self, parsed):
        """
        1. Named labels  — '[ LABELNAME ] comment lines -> lineno: name
        2. Pseudo-labels — GOTO/GOSUB targets with no named label -> LABEL_<n>
        """
        named = {}
        for entry in parsed:
            if entry["lineno"] is None:
                continue
            m = re.match(r"^'\[\s*([A-Za-z_]\w*)\s*\]$", entry["content"].strip())
            if m:
                named[entry["lineno"]] = m.group(1)

        jump_targets = set()
        for entry in parsed:
            if entry["lineno"] is None:
                continue
            code = re.sub(r"\s*'.*$", "", entry["content"])
            for m in re.finditer(r"\b(?:GOTO|GOSUB)\s+(\d+)", code, re.IGNORECASE):
                jump_targets.add(int(m.group(1)))

        label_map = dict(named)
        for target in jump_targets:
            if target not in label_map:
                label_map[target] = f"LABEL_{target}"

        return label_map

    # -----------------------------
    # PASS 3: EMIT SOURCE
    # -----------------------------
    def emit(self, parsed, label_map):
        pseudo_linenos = {ln for ln, name in label_map.items() if name.startswith("LABEL_")}
        output = []

        for entry in parsed:
            lineno = entry["lineno"]
            content = entry["content"]

            if lineno is None:
                output.append("")
                continue

            # Named label comment -> LABELNAME:
            m = re.match(r"^'\[\s*([A-Za-z_]\w*)\s*\]$", content.strip())
            if m:
                output.append(f"{m.group(1)}:")
                continue

            # Pseudo-label before this line
            if lineno in pseudo_linenos:
                output.append(f"LABEL_{lineno}:")

            # Strip trailing ' >> [ LABEL ] annotation
            content = re.sub(r"\s*'\s*>>\s*\[.*?\]\s*$", "", content)

            # GOTO/GOSUB <n> -> GOTO/GOSUB LABELNAME
            def replace_jump(match):
                kw = match.group(1)
                target = int(match.group(2))
                return f"{kw} {label_map.get(target, f'LABEL_{target}')}"

            content = re.sub(
                r"\b(GOTO|GOSUB)\s+(\d+)",
                replace_jump,
                content,
                flags=re.IGNORECASE,
            )

            output.append(content)

        return output

    def run(self, src_lines):
        """Parse, build label map and emit. Returns output lines."""
        parsed = self.parse(src_lines)
        label_map = self.build_label_map(parsed)
        return self.emit(parsed, label_map)
