import os

from flask import Flask
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

app = Flask(__name__)

TENANT = os.environ.get("TENANT_NAME", "unknown")

REQUESTS = Counter("tenant_app_requests_total", "Requests served by the home page")


@app.route("/")
def home():
    REQUESTS.inc()
    return f"Hello from tenant {TENANT}!\n"


@app.route("/healthz")
def healthz():
    return "ok\n"


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)