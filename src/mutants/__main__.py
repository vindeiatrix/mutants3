import logging, os
from pathlib import Path

from mutants.repl.loop import main


def _setup_logging() -> None:
    level = logging.DEBUG if os.getenv("WORLD_DEBUG") == "1" else logging.INFO
    log_dir = Path("state/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "game.log"

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
    )


_setup_logging()

if __name__ == "__main__":
    main()
