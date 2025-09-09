def main():
    print("Mutants skeleton is ready. (No game code yet)")
    print("Type 'exit' to quit or 'help' for info.")
    try:
        while True:
            cmd = input("> ").strip().lower()
            if cmd in ("exit", "quit"):
                print("Goodbye.")
                return
            if cmd in ("help", "-h", "--help"):
                print("This is a placeholder CLI. Add your code under src/mutants/.")
                continue
            if not cmd:
                continue
            print("Not implemented in skeleton.")
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye.")
