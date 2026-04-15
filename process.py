#!/usr/bin/env python3
"""
gwlabel.py — GW-BASIC label tool

Usage:
  gwlabel.py expand   infile.pbas [outfile.bas]   # labelled -> numbered
  gwlabel.py collapse infile.bas  [outfile.pbas]  # numbered -> labelled

File names are always uppercased on output (DOS style).
Input lookup is case-insensitive; a prompt is shown if the casing differs.
"""

import re
import os
import sys
import fire
import shutil

STEP = 10
BLOCK_STEP = 100


# =============================================================================
# SHARED HELPERS
# =============================================================================

def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


def _write(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        for l in lines:
            f.write(l + "\n")


def _dos_name(path):
    """Return path with the basename uppercased (DOS style)."""
    dir_, base = os.path.split(path)
    return os.path.join(dir_, base.upper()) if dir_ else base.upper()


def _find_existing_ci(path):
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


def _resolve_infile(path, yes:bool=False):
    """
    Locate infile using case-insensitive matching.
    Prompts the user if the on-disk name differs from what was typed.
    Returns the resolved path, or exits on abort/not-found.
    """
    found = _find_existing_ci(path)
    if found is None:
        print(f"File not found: {path}", file=sys.stderr)
        raise SystemExit(1)

    actual = os.path.normpath(found)
    requested = os.path.normpath(path)
    if actual != requested:
        if not yes:
            answer = input(
                f"'{requested}' not found. Use '{actual}'? [Y/n] "
            ).strip().lower()
            if answer == "n":
                raise SystemExit(1)
        
    uppercased = _dos_name(actual)
    if actual != uppercased:
        answer = input(
            f"Delete '{actual}' and save as '{uppercased}'? [Y/n] "
        ).strip().lower()
        if answer == "y":    
            shutil.move(actual, uppercased)
            actual = uppercased

    return actual


def _resolve_outfile(infile, outfile, yes:bool):
    """
    Uppercase the outfile name (DOS style), then handle three conflict cases:
      1. A differently-cased variant exists  -> ask to delete it and write uppercased
      2. The exact uppercased target exists  -> ask to overwrite
      3. The target resolves to the infile   -> ask to overwrite
    Returns the final path to write, or exits on abort.
    """
    dos = _dos_name(outfile)
    found = _find_existing_ci(outfile)

    if found is not None:
        actual = os.path.normpath(found)
        dos_norm = os.path.normpath(dos)
        in_norm = os.path.normpath(infile)

        if actual == in_norm:
            if not yes:
                answer = input(
                    f"Output '{dos}' is the same file as the input. Overwrite? [y/N] "
                ).strip().lower()
                if answer != "y":
                    raise SystemExit(1)
        elif actual != dos_norm:
            # e.g. NAME.bas exists, we want to write NAME.BAS
            if not yes:
                answer = input(
                    f"'{actual}' exists with different casing. "
                    f"Delete it and save as '{dos}'? [Y/n] "
                ).strip().lower()
                if answer == "n":
                    raise SystemExit(1)
            os.remove(actual)
        else:
            if not yes:
                answer = input(f"'{dos}' already exists. Overwrite? [Y/n] ").strip().lower()
                if answer == "n":
                    raise SystemExit(1)

    return dos


# =============================================================================
# EXPANDER  (.pbas -> .bas)
# =============================================================================

class GWExpander:
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
        snapping labelled blocks to the next BLOCK_STEP boundary.
        """
        block_starts = {}
        line_no = STEP

        for i, b in enumerate(blocks):
            if b["label"]:
                if line_no % BLOCK_STEP != 0:
                    line_no = (line_no // BLOCK_STEP + 1) * BLOCK_STEP
                block_starts[i] = line_no
                line_no += STEP  # label comment line
            else:
                block_starts[i] = line_no

            for line in b["lines"]:
                if line.strip():
                    line_no += STEP

        return block_starts

    def emit(self, blocks, label_map):
        block_starts = self.compute_block_starts(blocks)
        label_to_line = {label: block_starts[idx] for label, idx in label_map.items()}

        output = []
        line_no = STEP

        for i, b in enumerate(blocks):
            if b["label"]:
                line_no = block_starts[i]
                output.append(f"{line_no} '[ {b['label'].upper()} ]")
                line_no += STEP

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
                line_no += STEP

        return output

    # -----------------------------
    # ENTRY
    # -----------------------------
    def convert(self, infile, outfile=None, yes:bool = False):
        infile = _resolve_infile(infile, yes)
        if outfile is None:
            outfile = _dos_name(os.path.splitext(infile)[0] + ".bas")
        outfile = _resolve_outfile(infile, outfile, yes)

        src = _read(infile)
        blocks = self.parse(src)
        blocks, label_map = self.resolve(blocks)
        out = self.emit(blocks, label_map)
        _write(outfile, out)
        print(f"Expanded {infile} -> {outfile}")


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

    # -----------------------------
    # ENTRY
    # -----------------------------
    def convert(self, infile, outfile=None, yes:bool=False):
        infile = _resolve_infile(infile)
        if outfile is None:
            outfile = _dos_name(os.path.splitext(infile)[0] + ".pbas")
        outfile = _resolve_outfile(infile, outfile, yes)

        raw = _read(infile)
        parsed = self.parse(raw)
        label_map = self.build_label_map(parsed)
        out = self.emit(parsed, label_map)
        _write(outfile, out)
        print(f"Collapsed {infile} -> {outfile}")


# =============================================================================
# ENTRY POINT
# =============================================================================

class GWLabel:
    def expand(self, infile, outfile=None, yes:bool = False):
        """Expand labelled pseudo-BASIC (.pbas) into numbered GW-BASIC (.bas)."""
        GWExpander().convert(infile, outfile, yes)

    def collapse(self, infile, outfile=None, yes:bool = False):
        """Collapse numbered GW-BASIC (.bas) into labelled pseudo-BASIC (.pbas)."""
        GWCollapser().convert(infile, outfile, yes)


if __name__ == "__main__":
    fire.Fire(GWLabel)