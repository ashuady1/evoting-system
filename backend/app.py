"""
app.py — Flask entry point.

Serves the JSON API (voter/admin/dev blueprints) and the static frontend
(plain HTML/CSS/JS in ../frontend) from the same server, so there's only
one process to run for the whole demo.
"""

import os

from flask import Flask, jsonify
from database.db import get_connection, IS_POSTGRES
from routes.voter_routes import voter_bp
from routes.admin_routes import admin_bp
from routes.dev_routes import dev_bp

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.register_blueprint(voter_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(dev_bp)  # demo convenience only — see routes/dev_routes.py


@app.route("/")
def voter_portal():
    return app.send_static_file("index.html")


@app.route("/admin")
def admin_portal():
    return app.send_static_file("admin.html")


@app.route("/health")
def health():
    """Hit this once your server is running to confirm everything is set up."""
    try:
        conn = get_connection()
        if IS_POSTGRES:
            tables = conn.execute(
                "SELECT table_name AS name FROM information_schema.tables WHERE table_schema = 'public'"
            ).fetchall()
        else:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        conn.close()
        return jsonify({
            "status": "ok",
            "database": "PostgreSQL" if IS_POSTGRES else "SQLite",
            "tables": [t["name"] for t in tables]
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
