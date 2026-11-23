"""The `review` command. Only `--version` works until the reviewer lands (roadmap task 1.9)."""

from typing import Annotated

import typer

from reviewer import __version__

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def review(
    repository: Annotated[str, typer.Argument(help="The repository to review, as owner/repo.")],
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Print the version."
        ),
    ] = False,
) -> None:
    """Review a public GitHub repository for production readiness."""
    typer.echo("The reviewer is not implemented yet (roadmap task 1.9).", err=True)
    raise typer.Exit(code=2)
