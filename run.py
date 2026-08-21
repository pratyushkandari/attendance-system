import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # On Windows / dev, use standard server; on Linux / Cloud, run Gunicorn WSGI
    if os.name == "nt":
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        try:
            from gunicorn.app.base import BaseApplication

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
            print(f"[PROD WSGI] Starting Gunicorn server on 0.0.0.0:{port} (1 worker, 4 threads)")
            StandaloneApplication(app, options).run()
        except Exception as e:
            print(f"[WSGI FALLBACK] Starting standard server ({e}) on 0.0.0.0:{port}")
            app.run(host="0.0.0.0", port=port)