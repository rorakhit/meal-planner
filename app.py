"""
Weekly Meal Plan & Grocery List Builder

Runs on Railway with APScheduler for automatic Sunday meal generation
and Resend for email delivery.
"""

import logging
import os
from pathlib import Path

from flask import Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def create_app():
    app = Flask(__name__, template_folder=Path(__file__).parent / "templates")

    from weeks_rations.routes import bp
    app.register_blueprint(bp)

    from weeks_rations.scheduler import scheduler
    scheduler.start()

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    app.run(host="0.0.0.0", port=port, debug=False)
