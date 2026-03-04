"""Rich-based logging configuration."""

from rich.console import Console
from rich.logging import RichHandler
import logging

console = Console()


def get_logger(name: str) -> logging.Logger:
    """Return a logger with Rich handler."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = RichHandler(
            console=console,
            show_path=False,
            markup=True,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
