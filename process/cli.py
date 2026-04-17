"""
process/cli.py — GW-BASIC label compiler CLI
"""

import os
import click
from pathlib import Path

from .core import (
    CompilerConfig,
    DEFAULT_STEP,
    DEFAULT_BLOCK_STEP,
    ErrorCollector,
    run,
)

from .fs import (
    read,
    write,
    dos_name,
    find_existing_ci,
)


# =============================================================================
# HELPERS
# =============================================================================

def is_dir_mode(path):
    p = Path(path)
    return p.is_dir()


def collect_files(root, ext):
    root = Path(root)
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() == ext
    )


def resolve_infile(path):
    try:
        found = find_existing_ci(path)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))
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
    if not errors:
        return

    for err in errors.errors:
        click.echo(err.format(), err=True)


# =============================================================================
# PIPELINE
# =============================================================================

def run_batch(files, in_root, out_root, cfg, ctx, dry, verbose):
    in_root = Path(in_root).resolve()
    out_root = Path(out_root)

    if not dry:
        out_root.mkdir(parents=True, exist_ok=True)

    for f in files:
        f = f.resolve()

        if verbose:
            click.echo(f"[expand] {f}", err=True)

        src = read(f)
        out, errors = run(src, str(f), cfg)

        # MULTI ERROR HANDLING
        if errors:
            print_errors(errors)
            ctx.exit(1)

        dst = map_outfile(in_root, f, out_root, ".bas")

        if dry:
            for line in out:
                click.echo(line)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            write(dst, out)


def run_single(infile, outfile, cfg, ctx, dry, verbose):
    infile = resolve_infile(infile)
    src = read(infile)

    out, errors = run(src, infile, cfg)

    # MULTI ERROR HANDLING
    if errors:
        print_errors(errors)
        ctx.exit(1)

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
@click.pass_context
@click.argument("infile")
@click.argument("outfile", required=False)
@click.option("-n", "--dry-run", is_flag=True)
@click.option("-v", "--verbose", is_flag=True)
@click.option("--step", default=DEFAULT_STEP)
@click.option("--block-step", default=DEFAULT_BLOCK_STEP)
def cli(ctx, infile, outfile, dry_run, verbose, step, block_step):
    """
    GW-BASIC label tool

    Examples:
        ./process.py game.pbas game.bas
        ./process.py ./src ./build
    """

    cfg = CompilerConfig(step, block_step)

    # DIRECTORY MODE
    if is_dir_mode(infile):
        if outfile is None:
            raise click.ClickException("Output directory required for batch mode")

        files = collect_files(infile, ".pbas")

        if not files:
            click.echo(f"Warning: no .pbas files found in {infile}", err=True)
            return

        run_batch(files, infile, outfile, cfg, ctx, dry_run, verbose)
        return

    # SINGLE FILE MODE
    run_single(infile, outfile, cfg, ctx, dry_run, verbose)


if __name__ == "__main__":
    cli()