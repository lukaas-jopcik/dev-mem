"""
app.py — Flask web dashboard for dev-mem.

Binds to 127.0.0.1:8888 only.
"""

from __future__ import annotations

import csv
import io
import json
import time
from collections import Counter
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
    Response,
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
    """Return 0-100 health score based on recent observation activity."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent_obs = _db._conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE project_id=? AND created_at>=?",
        (project_id, week_ago),
    ).fetchone()["n"]
    errors = _db._conn.execute(
        "SELECT COALESCE(SUM(count),0) AS n FROM errors WHERE project_id=?",
        (project_id,),
    ).fetchone()["n"]
    activity = min(70, recent_obs * 4)
    penalty = min(30, int(errors) * 3)
    return max(0, activity - penalty)


def _project_obs_stats(project_id: int) -> dict:
    """Return rich observation stats for a project card."""
    type_rows = _db._conn.execute(
        "SELECT type, COUNT(*) AS n FROM observations WHERE project_id=? GROUP BY type",
        (project_id,),
    ).fetchall()
    types = {r["type"] or "discovery": r["n"] for r in type_rows}
    total = sum(types.values())

    bounds = _db._conn.execute(
        "SELECT MIN(created_at) AS first, MAX(created_at) AS last FROM observations WHERE project_id=?",
        (project_id,),
    ).fetchone()
    active_days = _db._conn.execute(
        "SELECT COUNT(DISTINCT DATE(created_at)) AS n FROM observations WHERE project_id=?",
        (project_id,),
    ).fetchone()["n"]

    concept_rows = _db._conn.execute(
        "SELECT concepts FROM observations WHERE project_id=? AND concepts != '[]' LIMIT 500",
        (project_id,),
    ).fetchall()
    all_concepts: list[str] = []
    for row in concept_rows:
        try:
            all_concepts.extend(json.loads(row["concepts"]))
        except Exception:
            pass
    top_concepts = [c for c, _ in Counter(all_concepts).most_common(6) if c and len(c) < 30]

    return {
        "total": total,
        "types": types,
        "last_activity": (bounds["last"] or "")[:10],
        "first_activity": (bounds["first"] or "")[:10],
        "active_days": active_days,
        "top_concepts": top_concepts,
    }


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

    recent_obs = _db._conn.execute(
        "SELECT id, type, title, project, created_at FROM observations ORDER BY id DESC LIMIT 8"
    ).fetchall()
    obs_today = _db._conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()["n"]
    active_projects_today = _db._conn.execute(
        "SELECT COUNT(DISTINCT project_id) AS n FROM observations "
        "WHERE created_at LIKE ? AND project_id IS NOT NULL", (f"{today}%",)
    ).fetchone()["n"]
    total_obs = _db._conn.execute("SELECT COUNT(*) AS n FROM observations").fetchone()["n"]

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
        recent_obs=[dict(o) for o in recent_obs],
        obs_today=obs_today,
        active_projects_today=active_projects_today,
        total_obs=total_obs,
    )


@app.route("/projects")
def projects():
    rows = _db._conn.execute(
        "SELECT * FROM projects WHERE active=1 ORDER BY last_accessed DESC, name"
    ).fetchall()
    git_cards = []
    local_cards = []
    for r in rows:
        pid = r["id"]
        r_dict = dict(r)
        obs = _project_obs_stats(pid)
        commit_count = _db._conn.execute(
            "SELECT COUNT(*) AS n FROM git_events WHERE project_id=?", (pid,)
        ).fetchone()["n"]
        card = {
            **r_dict,
            "commit_count": commit_count,
            "last_activity": obs["last_activity"] or (r_dict.get("last_accessed") or "")[:10],
            "first_activity": obs["first_activity"],
            "health": _project_health(pid),
            "is_git": r_dict.get("is_git", 0),
            "obs_total": obs["total"],
            "obs_types": obs["types"],
            "active_days": obs["active_days"],
            "top_concepts": obs["top_concepts"],
        }
        if card["is_git"]:
            git_cards.append(card)
        else:
            local_cards.append(card)
    return render_template("projects.html", git_cards=git_cards, local_cards=local_cards)


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
    recent_obs = _db._conn.execute(
        "SELECT id, type, title, narrative, created_at FROM observations "
        "WHERE project_id=? ORDER BY id DESC LIMIT 15",
        (pid,),
    ).fetchall()
    session_sums = _db._conn.execute(
        "SELECT request, completed, files_read, files_edited, created_at "
        "FROM session_summaries WHERE project_id=? ORDER BY created_at DESC LIMIT 10",
        (pid,),
    ).fetchall()
    obs_stats = _project_obs_stats(pid)
    stats = _db.get_today_stats(pid)
    return render_template(
        "project_detail.html",
        project=dict(row),
        commits=[dict(c) for c in commits],
        errors=[dict(e) for e in errors],
        learnings=[dict(l) for l in learnings_rows],
        recent_obs=[dict(o) for o in recent_obs],
        session_sums=[dict(s) for s in session_sums],
        obs_stats=obs_stats,
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
    # Fallback: show observations from that day grouped by project
    obs_by_project: list[dict] = []
    if not rows:
        obs_rows = _db._conn.execute(
            "SELECT o.type, o.title, o.narrative, p.name AS project_name "
            "FROM observations o LEFT JOIN projects p ON o.project_id=p.id "
            "WHERE o.created_at LIKE ? ORDER BY p.name, o.id DESC",
            (f"{date}%",),
        ).fetchall()
        by_proj: dict[str, list] = {}
        for o in obs_rows:
            pname = o["project_name"] or "General"
            by_proj.setdefault(pname, []).append(dict(o))
        obs_by_project = [{"project": k, "obs": v} for k, v in by_proj.items()]
    try:
        dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        prev_date = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
        next_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        prev_date = next_date = date
    return render_template(
        "daily.html",
        date=date,
        summaries=[dict(r) for r in rows],
        obs_by_project=obs_by_project,
        prev_date=prev_date,
        next_date=next_date,
    )


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


@app.route("/memory")
def memory():
    project_filter = request.args.get("project", "")
    type_filter = request.args.get("type", "")
    search_query = request.args.get("q", "")
    limit = int(request.args.get("limit", 50))

    try:
        import sqlite3 as _sqlite3
        from dev_mem.memory.observations import search_observations, list_observations

        conn = _sqlite3.connect(str(DB_PATH))
        conn.row_factory = _sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        try:
            if search_query:
                observations = search_observations(
                    conn, search_query,
                    limit=limit,
                    project=project_filter or None,
                    obs_type=type_filter or None,
                )
            else:
                observations = list_observations(
                    conn,
                    limit=limit,
                    project=project_filter or None,
                    obs_type=type_filter or None,
                )

            obs_types = [r[0] for r in conn.execute(
                "SELECT DISTINCT type FROM observations WHERE type != '' ORDER BY type"
            ).fetchall()]

            total = conn.execute("SELECT COUNT(*) AS n FROM observations").fetchone()["n"]
        except Exception:  # noqa: BLE001
            observations = []
            obs_types = []
            total = 0
        finally:
            conn.close()
    except ImportError:
        observations = []
        obs_types = []
        total = 0

    all_projects = _all_projects()
    return render_template(
        "memory.html",
        observations=observations,
        obs_types=obs_types,
        total=total,
        project_filter=project_filter,
        type_filter=type_filter,
        search_query=search_query,
        projects=all_projects,
    )


@app.route("/api/live")
def api_live():
    """Server-Sent Events endpoint — pushes live stats every 3 seconds."""
    def _stream():
        import sqlite3 as _sqlite3
        while True:
            try:
                # Open a fresh connection per tick to always get latest data
                conn = _sqlite3.connect(str(DB_PATH))
                conn.row_factory = _sqlite3.Row
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                def _count(table: str, ts_col: str = "ts") -> int:
                    row = conn.execute(
                        f"SELECT COUNT(*) AS n FROM {table} WHERE {ts_col} LIKE ?",
                        (f"{today}%",),
                    ).fetchone()
                    return row["n"] if row else 0

                counts = {
                    "commands":        _count("commands"),
                    "git_events":      _count("git_events"),
                    "claude_sessions": _count("claude_sessions"),
                    "errors":          _count("errors", "last_seen"),
                }
                recent_cmd = conn.execute(
                    "SELECT cmd, ts FROM commands ORDER BY ts DESC LIMIT 5"
                ).fetchall()
                recent_commits = conn.execute(
                    "SELECT message, ts FROM git_events ORDER BY ts DESC LIMIT 5"
                ).fetchall()
                obs_total = conn.execute(
                    "SELECT COUNT(*) AS n FROM observations"
                ).fetchone()["n"]
                recent_obs = conn.execute(
                    "SELECT id, type, title, narrative, project, created_at "
                    "FROM observations ORDER BY id DESC LIMIT 10"
                ).fetchall()

                conn.close()

                data = json.dumps({
                    **counts,
                    "observations": obs_total,
                    "recent_commands": [
                        {"cmd": r["cmd"], "ts": r["ts"]} for r in recent_cmd
                    ],
                    "recent_commits": [
                        {"message": r["message"][:80], "ts": r["ts"]} for r in recent_commits
                    ],
                    "recent_observations": [
                        {
                            "id": r["id"],
                            "type": r["type"] or "discovery",
                            "title": r["title"] or "",
                            "narrative": (r["narrative"] or "")[:200],
                            "project": r["project"] or "",
                            "created_at": (r["created_at"] or "")[:16],
                        }
                        for r in recent_obs
                    ],
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
                yield f"data: {data}\n\n"
            except Exception:  # noqa: BLE001
                yield "data: {}\n\n"
            time.sleep(3)

    return Response(
        _stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/team")
def team():
    cc_sessions = _db._conn.execute(
        "SELECT ccs.*, p.name AS project_name FROM claude_code_sessions ccs "
        "LEFT JOIN projects p ON p.id=ccs.project_id "
        "ORDER BY ccs.started_at DESC LIMIT 20"
    ).fetchall()
    ss = _db._conn.execute(
        "SELECT s.*, p.name AS project_name FROM session_summaries s "
        "LEFT JOIN projects p ON p.id=s.project_id "
        "ORDER BY s.created_at DESC LIMIT 30"
    ).fetchall()
    tool_stats = _db._conn.execute(
        "SELECT tool, COUNT(*) AS n FROM claude_sessions GROUP BY tool ORDER BY n DESC LIMIT 12"
    ).fetchall()
    today = _today()
    today_obs = _db._conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()["n"]
    today_projects = [
        r[0] for r in _db._conn.execute(
            "SELECT DISTINCT p.name FROM observations o "
            "JOIN projects p ON o.project_id=p.id WHERE o.created_at LIKE ?",
            (f"{today}%",),
        ).fetchall()
    ]
    week_obs = _db._conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE created_at >= ?",
        ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),),
    ).fetchone()["n"]
    return render_template(
        "team.html",
        cc_sessions=[dict(s) for s in cc_sessions],
        session_summaries=[dict(s) for s in ss],
        tool_stats=[dict(t) for t in tool_stats],
        today_obs=today_obs,
        week_obs=week_obs,
        today_projects=today_projects,
        today=today,
    )


@app.route("/api/obs-stats")
def api_obs_stats():
    days = int(request.args.get("days", 30))
    start_dt = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    project_counts = _db._conn.execute(
        "SELECT p.name, COUNT(o.id) AS n FROM observations o "
        "JOIN projects p ON o.project_id=p.id "
        "WHERE o.created_at >= ? GROUP BY p.id ORDER BY n DESC LIMIT 12",
        (start_dt,),
    ).fetchall()
    daily_obs = _db._conn.execute(
        "SELECT DATE(created_at) AS d, COUNT(*) AS n FROM observations "
        "WHERE created_at >= ? GROUP BY DATE(created_at) ORDER BY d",
        (start_dt,),
    ).fetchall()
    type_breakdown = _db._conn.execute(
        "SELECT type, COUNT(*) AS n FROM observations "
        "WHERE created_at >= ? GROUP BY type ORDER BY n DESC",
        (start_dt,),
    ).fetchall()
    hourly = _db._conn.execute(
        "SELECT CAST(strftime('%H', created_at) AS INTEGER) AS hour, "
        "CAST(strftime('%w', created_at) AS INTEGER) AS dow, COUNT(*) AS n "
        "FROM observations WHERE created_at >= ? GROUP BY hour, dow",
        (start_dt,),
    ).fetchall()

    return jsonify({
        "project_counts": [{"project": r["name"], "count": r["n"]} for r in project_counts],
        "daily_obs": [{"date": r["d"], "count": r["n"]} for r in daily_obs],
        "type_breakdown": [{"type": r["type"] or "discovery", "count": r["n"]} for r in type_breakdown],
        "heatmap": [{"hour": r["hour"], "dow": r["dow"], "count": r["n"]} for r in hourly],
    })


def run():
    app.run(host="127.0.0.1", port=8888, debug=False, threaded=True)


if __name__ == "__main__":
    run()
