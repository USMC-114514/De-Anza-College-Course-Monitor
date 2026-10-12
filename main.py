"""Terminal app: search courses, keep a watchlist and poll it.

    python main.py
"""

from engine.terminal.app import main

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
