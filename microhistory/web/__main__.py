"""Entry point: python -m microhistory.web"""

from __future__ import annotations

import webbrowser

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    import uvicorn
    from microhistory.web.app import create_app

    app = create_app()

    host = "127.0.0.1"
    port = 8000
    print(f"\n  MicroHistory Web UI: http://{host}:{port}\n")

    # Open browser automatically
    webbrowser.open(f"http://{host}:{port}")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
