#!/usr/bin/env python3
"""
preprocess.py — GW-BASIC label compiler

Supports:
- LABEL:
- GOTO LABEL
- GOSUB LABEL
- line numbering in blocks (100s) + steps of 10
- uppercase output except strings
"""

import re
import fire

STEP = 10
BLOCK_STEP = 100


class GWCompiler:
    # -----------------------------
    # IO
    # -----------------------------
    def read(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]

    def write(self, path, lines):
        with open(path, "w", encoding="utf-8") as f:
            for l in lines:
                f.write(l + "\n")

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
                # start new block
                if current["label"] is not None or current["lines"]:
                    blocks.append(current)

                current = {
                    "label": m.group(1),
                    "lines": []
                }

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
        block_index = 0

        # assign block indices first
        for b in blocks:
            if b["label"]:
                label_to_block[b["label"]] = block_index
            block_index += 1

        # replace GOTOs symbolically
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
                    flags=re.IGNORECASE
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

    def count_emitted_lines(self, block):
        """Count how many numbered lines a block will produce (skipping blank lines)."""
        count = 0
        if block["label"]:
            count += 1  # the '[ LABEL ] comment line
        for line in block["lines"]:
            if line.strip():
                count += 1
        return count

    def compute_block_starts(self, blocks):
        """
        Pre-scan pass: compute the actual starting line number for each block.
        Each labelled block starts at a multiple of BLOCK_STEP that is large
        enough to fit all lines of the previous block, rounded up to the next
        BLOCK_STEP boundary.
        """
        block_starts = {}   # block_index -> first line number of that block
        line_no = STEP      # global line counter starts at STEP (10)

        for i, b in enumerate(blocks):
            if b["label"]:
                # Round up to the next BLOCK_STEP boundary
                if line_no % BLOCK_STEP != 0:
                    line_no = (line_no // BLOCK_STEP + 1) * BLOCK_STEP
                block_starts[i] = line_no
                line_no += STEP  # the label comment takes one line number
            else:
                block_starts[i] = line_no

            # Advance line_no for each real (non-blank) line in the block
            for line in b["lines"]:
                if line.strip():
                    line_no += STEP

        return block_starts

    def emit(self, blocks, label_map):
        # Pre-compute the real starting line for every block
        block_starts = self.compute_block_starts(blocks)

        # Build a label -> actual line number map for GOTO resolution
        label_to_line = {}
        for label, block_index in label_map.items():
            label_to_line[label] = block_starts[block_index]

        output = []
        line_no = STEP

        for i, b in enumerate(blocks):
            if b["label"]:
                # Snap to the pre-computed start for this block
                line_no = block_starts[i]
                output.append(f"{line_no} '[ {b['label'].upper()} ]")
                line_no += STEP

            for line in b["lines"]:
                if not line.strip():
                    output.append("")  # spacer
                    continue

                # Resolve symbolic gotos to actual line numbers
                def fix(match, _label_to_line=label_to_line):
                    label = match.group(2)
                    target_line = _label_to_line[label]
                    return f"{match.group(1)} {target_line} ' >> [ {label} ]"

                line = re.sub(
                    r"\b(GOTO|GOSUB)\s+@([A-Za-z_]\w*)@",
                    fix,
                    line
                )

                line = self.smart_upper(line)

                output.append(f"{line_no} {line}")
                line_no += STEP

        return output

    # -----------------------------
    # ENTRY
    # -----------------------------
    def convert(self, infile, outfile):
        src = self.read(infile)

        blocks = self.parse(src)
        blocks, label_map = self.resolve(blocks)
        out = self.emit(blocks, label_map)

        self.write(outfile, out)

        print(f"Converted {infile} -> {outfile}")


if __name__ == "__main__":
    fire.Fire(GWCompiler().convert)