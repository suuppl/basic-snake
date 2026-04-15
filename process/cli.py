"""
process/cli.py — Click CLI for gwlabel / process.py

All file resolution, dry-run, and verbosity concerns live here.
Core processing is delegated to process.core.
"""

import os
import click

from .core import (
    GWExpander, GWCollapser,
    DEFAULT_STEP, DEFAULT_BLOCK_STEP,
    read, write, dos_name, find_existing_ci,
)


# =============================================================================
# FILE RESOLUTION  (DOS-style, case-insensitive)
# =============================================================================

def _resolve_infile(path, yes):
    """
    Locate infile using case-insensitive matching.
    Prompts if the on-disk name differs from what was typed.
    Returns the resolved path, or exits on abort/not-found.
    """
    found = find_existing_ci(path)
    if found is None:
        click.echo(f"File not found: {path}", err=True)
        raise SystemExit(1)

    actual = os.path.normpath(found)
    requested = os.path.normpath(path)

    if actual != requested and not yes:
        if not click.confirm(f"'{requested}' not found. Use '{actual}'?", default=True):
            raise SystemExit(1)

    return actual


def _resolve_outfile(infile, outfile, yes, dry_run, verbose):
    """
    Uppercase the outfile name (DOS style), handle three conflict cases:
      1. A differently-cased variant exists  -> ask to delete and write uppercased
      2. The exact uppercased target exists  -> ask to overwrite
      3. The target resolves to the infile   -> ask to overwrite
    In dry-run mode, conflict checks are skipped (nothing will be written).
    Returns the final DOS-cased path.
    """
    dos = dos_name(outfile)

    if dry_run:
        if verbose:
            click.echo(f"[dry-run] Would write to: {dos}", err=True)
        return dos

    found = find_existing_ci(outfile)

    if found is not None:
        actual = os.path.normpath(found)
        dos_norm = os.path.normpath(dos)
        in_norm = os.path.normpath(infile)

        if actual == in_norm:
            if not yes and not click.confirm(
                f"Output '{dos}' is the same file as the input. Overwrite?",
                default=False,
            ):
                raise SystemExit(1)

        elif actual != dos_norm:
            # e.g. NAME.bas exists on disk, we want NAME.BAS
            if verbose:
                click.echo(f"[conflict] '{actual}' has different casing from '{dos}'", err=True)
            if not yes and not click.confirm(
                f"'{actual}' exists with different casing. Delete it and save as '{dos}'?",
                default=True,
            ):
                raise SystemExit(1)
            if verbose:
                click.echo(f"[delete] {actual}", err=True)
            os.remove(actual)

        else:
            if not yes and not click.confirm(
                f"'{dos}' already exists. Overwrite?",
                default=True,
            ):
                raise SystemExit(1)

    return dos


# =============================================================================
# CLI
# =============================================================================

@click.group()
def cli():
    """GW-BASIC label tool.

    Converts between labelled pseudo-BASIC (.pbas) and
    numbered GW-BASIC (.bas). File names are always uppercased
    on output (DOS style).
    """
    pass


# ── expand ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("infile")
@click.argument("outfile", required=False)
@click.option("--yes",        "-y", is_flag=True,
              help="Answer yes to all confirmation prompts.")
@click.option("--dry-run",    "-n", is_flag=True,
              help="Print output to stdout instead of writing a file.")
@click.option("--verbose",    "-v", is_flag=True,
              help="Show extra detail about what is happening.")
@click.option("--step",       type=int, default=DEFAULT_STEP,       show_default=True,
              help="Line-number increment within a block.")
@click.option("--block-step", type=int, default=DEFAULT_BLOCK_STEP, show_default=True,
              help="Line-number boundary between labelled blocks.")
def expand(infile, outfile, yes, dry_run, verbose, step, block_step):
    """Expand labelled pseudo-BASIC (.pbas) into numbered GW-BASIC (.bas)."""

    infile = _resolve_infile(infile, yes)

    if outfile is None:
        outfile = dos_name(os.path.splitext(infile)[0] + ".bas")

    outfile = _resolve_outfile(infile, outfile, yes, dry_run, verbose)

    if verbose:
        click.echo(f"[expand] {infile} -> {outfile}  "
                   f"(step={step}, block-step={block_step})", err=True)

    src = read(infile)
    expander = GWExpander(step=step, block_step=block_step)
    out = expander.run(src)

    if dry_run:
        for line in out:
            click.echo(line)
    else:
        write(outfile, out)
        click.echo(f"Expanded {infile} -> {outfile}"
                   + (f"  ({len(out)} lines)" if verbose else ""))


# ── collapse ──────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("infile")
@click.argument("outfile", required=False)
@click.option("--yes",     "-y", is_flag=True,
              help="Answer yes to all confirmation prompts.")
@click.option("--dry-run", "-n", is_flag=True,
              help="Print output to stdout instead of writing a file.")
@click.option("--verbose", "-v", is_flag=True,
              help="Show extra detail about what is happening.")
def collapse(infile, outfile, yes, dry_run, verbose):
    """Collapse numbered GW-BASIC (.bas) into labelled pseudo-BASIC (.pbas)."""

    infile = _resolve_infile(infile, yes)

    if outfile is None:
        outfile = dos_name(os.path.splitext(infile)[0] + ".pbas")

    outfile = _resolve_outfile(infile, outfile, yes, dry_run, verbose)

    if verbose:
        click.echo(f"[collapse] {infile} -> {outfile}", err=True)

    src = read(infile)
    collapser = GWCollapser()
    out = collapser.run(src)

    if dry_run:
        for line in out:
            click.echo(line)
    else:
        write(outfile, out)
        click.echo(f"Collapsed {infile} -> {outfile}"
                   + (f"  ({len(out)} lines)" if verbose else ""))
