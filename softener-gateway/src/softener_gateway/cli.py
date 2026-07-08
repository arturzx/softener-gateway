import asyncio
import logging
from pathlib import Path

import click

from softener_gateway.app import run_gateway
from softener_gateway.config import ConfigError, load_config


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=False),
    help="Path to YAML configuration file.",
)
@click.option("-v", "--verbose", count=True, help="Increase log verbosity.")
def main(config_path: Path | None, verbose: int) -> None:
    configure_logging(verbose)

    try:
        config = load_config(config_path)
        asyncio.run(run_gateway(config))
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


def configure_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=level,
    )
