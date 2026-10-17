"""Start the monitoring app on this computer.

Run this file with the virtual environment's Python. It is the only
file you need to execute to open the starter app.
"""

from app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config["DEBUG"],
    )
