import logging, os
from mutants.repl.loop import main

level = logging.DEBUG if os.getenv("WORLD_DEBUG") == "1" else logging.INFO
logging.basicConfig(
    level=level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

if __name__ == "__main__":
    main()
