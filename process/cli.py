"""
process/cli.py — GW-BASIC label compiler CLI
"""

import os
import click
from pathlib import Path

from .core import (
    Compiler,
    DEFAULT_STEP,
    DEFAULT_BLOCK_STEP,
    read,
    write,
    dos_name,
    find_existing_ci,
    ErrorCollector,
)


# =============================================================================
# HELPERS
# =============================================================================

def is_dir_mode(path):
    p = Path(path)
    return p.is_dir() or p.suffix == ""


def collect_files(root, ext):
    root = Path(root)
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() == ext
    )


def resolve_infile(path):
    found = find_existing_ci(path)
    if not found:
        raise click.ClickException(f"File not found: {path}")
    return os.path.normpath(found)


def map_outfile(in_root, infile, out_root, new_ext):
    rel = Path(infile).relative_to(in_root)
    out = Path(out_root) / rel.with_suffix(new_ext)
    return out.parent / out.name.upper()


# =============================================================================
# ERROR RENDERING
# =============================================================================

def print_errors(errors: ErrorCollector):
    if not errors or not errors.errors:
        return

    for err in errors.errors:
        click.echo(err.format(), err=True)


# =============================================================================
# PIPELINE
# =============================================================================

def run_batch(files, in_root, out_root, compiler, dry, verbose):
    out_root = Path(out_root)

    if not dry:
        out_root.mkdir(parents=True, exist_ok=True)

    for f in files:
        if verbose:
            click.echo(f"[expand] {f}", err=True)

        src = read(f)
        out, errors = compiler.run(src, str(f))

        # MULTI ERROR HANDLING
        if errors and errors.errors:
            print_errors(errors)
            raise SystemExit(1)

        dst = map_outfile(in_root, f, out_root, ".bas")

        if dry:
            for line in out:
                click.echo(line)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            write(dst, out)


def run_single(infile, outfile, compiler, dry, verbose):
    infile = resolve_infile(infile)
    src = read(infile)

    out, errors = compiler.run(src, infile)

    # MULTI ERROR HANDLING
    if errors and errors.errors:
        print_errors(errors)
        raise SystemExit(1)

    if outfile is None:
        outfile = dos_name(Path(infile).with_suffix(".bas"))

    dst = Path(outfile)

    if verbose:
        click.echo(f"[expand] {infile} -> {dst}", err=True)

    if dry:
        for line in out:
            click.echo(line)
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    write(dst, out)

    click.echo(f"Expanded {infile} -> {dst}")


# =============================================================================
# CLI ENTRY
# =============================================================================

@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("infile")
@click.argument("outfile", required=False)
@click.option("-n", "--dry-run", is_flag=True)
@click.option("-v", "--verbose", is_flag=True)
@click.option("--step", default=DEFAULT_STEP)
@click.option("--block-step", default=DEFAULT_BLOCK_STEP)
def cli(infile, outfile, dry_run, verbose, step, block_step):
    """
    GW-BASIC label tool

    Examples:
        ./process.py game.pbas game.bas
        ./process.py ./src ./build
    """

    compiler = Compiler(step, block_step)

    # DIRECTORY MODE
    if is_dir_mode(infile):
        if outfile is None:
            raise click.ClickException("Output directory required for batch mode")

        files = collect_files(infile, ".pbas")
        run_batch(files, infile, outfile, compiler, dry_run, verbose)
        return

    # SINGLE FILE MODE
    run_single(infile, outfile, compiler, dry_run, verbose)


if __name__ == "__main__":
    cli()