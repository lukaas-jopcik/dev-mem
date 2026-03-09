"""
app.py — Flask web dashboard for dev-mem.

Binds to 127.0.0.1:8888 only.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    make_response,
    redirect,
    url_for,
)
from markupsafe import Markup

from dev_mem.db import Database
from dev_mem.settings import Settings, DB_PATH

app = Flask(__name__, template_folder="templates", static_folder="static")


def create_app(db_path: str | None = None, port: int = 8888) -> Flask:
    """Application factory for dev-mem web dashboard."""
    if db_path:
        app.config["DB_PATH"] = db_path
    app.config["PORT"] = port
    return app


_settings = Settings()
_db = Database(DB_PATH)


# ---------------------------------------------------------------------------
# Jinja filters
# ---------------------------------------------------------------------------

def _safe_md(text: str) -> Markup:
    """Render markdown to safe HTML. Falls back to escaped text if markdown not installed."""
    try:
        import markdown as md_lib
        html = md_lib.markdown(text, extensions=["fenced_code", "tables"])
    except ImportError:
        from markupsafe import escape
        html = str(escape(text)).replace("\n", "<br>")
    return Markup(html)


app.jinja_env.filters["safe_md"] = _safe_md


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _date_range_start(days: int = 30) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _all_projects() -> list[dict]:
    rows = _db._conn.execute(
        "SELECT * FROM projects WHERE active = 1 ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def _project_health(project_id: int) -> int:
    """Return 0-100 health score for a project based on recent activity."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    commits = _db._conn.execute(
        "SELECT COUNT(*) AS n FROM git_events WHERE project_id=? AND ts>=?",
        (project_id, week_ago),
    ).fetchone()["n"]
    errors = _db._conn.execute(
        "SELECT COALESCE(SUM(count),0) AS n FROM errors WHERE project_id=? AND last_seen>=?",
        (project_id, week_ago),
    ).fetchone()["n"]
    score = min(100, commits * 10) - min(50, errors * 5)
    return max(0, score)


def _active_alerts() -> list[dict]:
    """Return simple rule-based alerts."""
    alerts = []
    threshold = _settings.get("error_alert_threshold", 3)
    rows = _db._conn.execute(
        "SELECT e.*, p.name AS project_name FROM errors e "
        "LEFT JOIN projects p ON p.id=e.project_id "
        "WHERE e.count >= ? ORDER BY e.count DESC LIMIT 10",
        (threshold,),
    ).fetchall()
    for r in rows:
        alerts.append({
            "type": "error",
            "message": f"Error seen {r['count']}x in {r['project_name'] or 'unknown'}: "
                       f"{r['error_text'][:80]}",
            "count": r["count"],
        })

    min_score = _settings.get("prompt_min_score_alert", 40)
    low = _db._conn.execute(
        "SELECT COUNT(*) AS n FROM prompts WHERE score > 0 AND score < ?",
        (min_score,),
    ).fetchone()["n"]
    if low:
        alerts.append({
            "type": "warning",
            "message": f"{low} prompt(s) have score below {min_score}",
            "count": low,
        })
    return alerts


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    today = _today()
    stats = _db.get_today_stats(None)

    commits = _db._conn.execute(
        "SELECT g.*, p.name AS project_name FROM git_events g "
        "LEFT JOIN projects p ON p.id=g.project_id "
        "ORDER BY g.ts DESC LIMIT 5"
    ).fetchall()

    learnings = _db._conn.execute(
        "SELECT l.*, p.name AS project_name FROM learnings l "
        "LEFT JOIN projects p ON p.id=l.project_id "
        "ORDER BY l.ts DESC LIMIT 3"
    ).fetchall()

    avg_score_row = _db._conn.execute(
        "SELECT AVG(score) AS avg FROM prompts WHERE score > 0"
    ).fetchone()
    avg_score = round(avg_score_row["avg"] or 0)

    alerts = _active_alerts()
    projects = _all_projects()

    return render_template(
        "index.html",
        stats=stats,
        commits=[dict(c) for c in commits],
        learnings=[dict(l) for l in learnings],
        avg_score=avg_score,
        alerts=alerts,
        projects=projects,
        today=today,
    )


@app.route("/projects")
def projects():
    rows = _db._conn.execute(
        "SELECT * FROM projects WHERE active=1 ORDER BY name"
    ).fetchall()
    cards = []
    for r in rows:
        pid = r["id"]
        commit_count = _db._conn.execute(
            "SELECT COUNT(*) AS n FROM git_events WHERE project_id=?", (pid,)
        ).fetchone()["n"]
        total_sec = _db._conn.execute(
            "SELECT COALESCE(SUM(duration_sec),0) AS s FROM sessions WHERE project_id=?", (pid,)
        ).fetchone()["s"]
        last_act = _db._conn.execute(
            "SELECT MAX(ts) AS t FROM commands WHERE project_id=?", (pid,)
        ).fetchone()["t"]
        cards.append({
            **dict(r),
            "commit_count": commit_count,
            "total_hours": round(total_sec / 3600, 1),
            "last_activity": (last_act or "")[:10],
            "health": _project_health(pid),
        })
    return render_template("projects.html", cards=cards)


@app.route("/project/<name>")
def project_detail(name: str):
    row = _db._conn.execute(
        "SELECT * FROM projects WHERE name=? AND active=1", (name,)
    ).fetchone()
    if not row:
        return redirect(url_for("projects"))
    pid = row["id"]
    commits = _db._conn.execute(
        "SELECT * FROM git_events WHERE project_id=? ORDER BY ts DESC LIMIT 20", (pid,)
    ).fetchall()
    errors = _db._conn.execute(
        "SELECT * FROM errors WHERE project_id=? ORDER BY count DESC LIMIT 10", (pid,)
    ).fetchall()
    learnings_rows = _db._conn.execute(
        "SELECT * FROM learnings WHERE project_id=? ORDER BY ts DESC LIMIT 10", (pid,)
    ).fetchall()
    stats = _db.get_today_stats(pid)
    return render_template(
        "project_detail.html",
        project=dict(row),
        commits=[dict(c) for c in commits],
        errors=[dict(e) for e in errors],
        learnings=[dict(l) for l in learnings_rows],
        stats=stats,
        health=_project_health(pid),
    )


@app.route("/analytics")
def analytics():
    projects = _all_projects()
    return render_template("analytics.html", projects=projects)


@app.route("/prompts")
def prompts():
    project_filter = request.args.get("project", "")
    min_score = int(request.args.get("min_score", 0))
    date_from = request.args.get("date_from", "")

    query = (
        "SELECT p.*, pr.name AS project_name FROM prompts p "
        "LEFT JOIN projects pr ON pr.id=p.project_id WHERE 1=1"
    )
    params: list[Any] = []
    if project_filter:
        query += " AND pr.name=?"
        params.append(project_filter)
    if min_score:
        query += " AND p.score>=?"
        params.append(min_score)
    if date_from:
        query += " AND p.ts>=?"
        params.append(date_from)
    query += " ORDER BY p.ts DESC LIMIT 200"

    rows = _db._conn.execute(query, params).fetchall()
    best = _db._conn.execute(
        "SELECT * FROM prompts ORDER BY score DESC LIMIT 1"
    ).fetchone()
    worst = _db._conn.execute(
        "SELECT * FROM prompts WHERE score > 0 ORDER BY score ASC LIMIT 1"
    ).fetchone()
    all_projects = _all_projects()
    return render_template(
        "prompts.html",
        prompts=[dict(r) for r in rows],
        best=dict(best) if best else None,
        worst=dict(worst) if worst else None,
        projects=all_projects,
        project_filter=project_filter,
        min_score=min_score,
        date_from=date_from,
    )


@app.route("/errors")
def errors():
    rows = _db._conn.execute(
        "SELECT e.*, p.name AS project_name FROM errors e "
        "LEFT JOIN projects p ON p.id=e.project_id "
        "ORDER BY e.count DESC LIMIT 100"
    ).fetchall()
    return render_template("errors.html", errors=[dict(r) for r in rows])


@app.route("/learnings")
def learnings():
    type_filter = request.args.get("type", "")
    query = (
        "SELECT l.*, p.name AS project_name FROM learnings l "
        "LEFT JOIN projects p ON p.id=l.project_id WHERE 1=1"
    )
    params: list[Any] = []
    if type_filter:
        query += " AND l.type=?"
        params.append(type_filter)
    query += " ORDER BY l.ts DESC LIMIT 200"
    rows = _db._conn.execute(query, params).fetchall()
    types = [r[0] for r in _db._conn.execute(
        "SELECT DISTINCT type FROM learnings WHERE type != '' ORDER BY type"
    ).fetchall()]
    return render_template(
        "learnings.html",
        learnings=[dict(r) for r in rows],
        types=types,
        type_filter=type_filter,
    )


@app.route("/daily/<date>")
def daily(date: str):
    rows = _db._conn.execute(
        "SELECT ds.*, p.name AS project_name FROM daily_summaries ds "
        "LEFT JOIN projects p ON p.id=ds.project_id "
        "WHERE ds.date=? ORDER BY p.name",
        (date,),
    ).fetchall()
    return render_template("daily.html", date=date, summaries=[dict(r) for r in rows])


@app.route("/daily")
def daily_today():
    return redirect(url_for("daily", date=_today()))


@app.route("/export", methods=["GET"])
def export_page():
    all_projects = _all_projects()
    return render_template("export.html", projects=all_projects, today=_today())


@app.route("/export", methods=["POST"])
def export_download():
    project_name = request.form.get("project", "")
    date_from = request.form.get("date_from", "")
    date_to = request.form.get("date_to", _today())
    fmt = request.form.get("format", "json")
    table = request.form.get("table", "commands")

    allowed = {"commands", "git_events", "errors", "prompts", "learnings"}
    if table not in allowed:
        table = "commands"

    query = f"SELECT * FROM {table} WHERE 1=1"
    params: list[Any] = []
    if project_name:
        pid_row = _db._conn.execute(
            "SELECT id FROM projects WHERE name=?", (project_name,)
        ).fetchone()
        if pid_row:
            query += " AND project_id=?"
            params.append(pid_row["id"])
    if date_from:
        query += " AND ts>=?"
        params.append(date_from)
    if date_to:
        query += " AND ts<=?"
        params.append(date_to + "T23:59:59")
    query += " ORDER BY ts DESC LIMIT 5000"

    rows = _db._conn.execute(query, params).fetchall()
    data = [dict(r) for r in rows]

    if fmt == "csv":
        buf = io.StringIO()
        if data:
            writer = csv.DictWriter(buf, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        resp = make_response(buf.getvalue())
        resp.headers["Content-Type"] = "text/csv"
        resp.headers["Content-Disposition"] = f"attachment; filename={table}.csv"
        return resp

    resp = make_response(json.dumps(data, indent=2, default=str))
    resp.headers["Content-Type"] = "application/json"
    resp.headers["Content-Disposition"] = f"attachment; filename={table}.json"
    return resp


@app.route("/api/stats")
def api_stats():
    days = int(request.args.get("days", 30))
    start = _date_range_start(days)

    score_rows = _db._conn.execute(
        "SELECT DATE(ts) AS d, AVG(score) AS avg_score "
        "FROM prompts WHERE score>0 AND ts>=? GROUP BY DATE(ts) ORDER BY d",
        (start,),
    ).fetchall()

    time_rows = _db._conn.execute(
        "SELECT p.name, COALESCE(SUM(s.duration_sec),0) AS total_sec "
        "FROM sessions s JOIN projects p ON p.id=s.project_id "
        "WHERE s.start_ts>=? GROUP BY p.name ORDER BY total_sec DESC LIMIT 10",
        (start,),
    ).fetchall()

    cmd_rows = _db._conn.execute(
        "SELECT CAST(strftime('%H', ts) AS INTEGER) AS hour, "
        "CAST(strftime('%w', ts) AS INTEGER) AS dow, COUNT(*) AS n "
        "FROM commands WHERE ts>=? GROUP BY hour, dow",
        (start,),
    ).fetchall()

    err_rows = _db._conn.execute(
        "SELECT e.error_text, e.count, p.name AS project_name "
        "FROM errors e LEFT JOIN projects p ON p.id=e.project_id "
        "ORDER BY e.count DESC LIMIT 10"
    ).fetchall()

    return jsonify({
        "score_trend": [
            {"date": r["d"], "score": round(r["avg_score"], 1)}
            for r in score_rows
        ],
        "time_per_project": [
            {"project": r["name"], "hours": round(r["total_sec"] / 3600, 2)}
            for r in time_rows
        ],
        "heatmap": [
            {"hour": r["hour"], "dow": r["dow"], "count": r["n"]}
            for r in cmd_rows
        ],
        "error_freq": [
            {"text": r["error_text"][:60], "count": r["count"], "project": r["project_name"]}
            for r in err_rows
        ],
    })


def run():
    app.run(host="127.0.0.1", port=8888, debug=False)


if __name__ == "__main__":
    run()
