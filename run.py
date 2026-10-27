import logging
import os

# Configure logging before the app package is imported: app.extensions connects to
# Redis at import time, and without a handler every INFO line (cache status, runbook
# log lines) would be silently dropped.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app import create_app  # noqa: E402

logger = logging.getLogger(__name__)

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # On Windows / dev, use standard server; on Linux / Cloud, run Gunicorn WSGI
    if os.name == "nt":
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        try:
            from gunicorn.app.base import BaseApplication
        except ImportError:
            # Only a missing Gunicorn falls back to Flask's server; Gunicorn startup errors
            # must surface instead of silently serving production traffic with a dev server.
            logger.warning("Gunicorn is not installed; starting Flask's development server on 0.0.0.0:%s", port)
            app.run(host="0.0.0.0", port=port)
        else:
            class StandaloneApplication(BaseApplication):
                def __init__(self, application, options=None):
                    self.options = options or {}
                    self.application = application
                    super().__init__()

                def load_config(self):
                    for key, value in self.options.items():
                        if key in self.cfg.settings and value is not None:
                            self.cfg.set(key.lower(), value)

                def load(self):
                    return self.application

            options = {
                "bind": f"0.0.0.0:{port}",
                "workers": 1,
                "threads": 4,
                "timeout": 120,
            }
            logger.info("Starting Gunicorn on 0.0.0.0:%s (1 worker, 4 threads)", port)
            StandaloneApplication(app, options).run()
