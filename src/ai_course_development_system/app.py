"""Minimal 2-page frontend: (1) prompt form, (2) per-agent debug outputs."""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, redirect, request, url_for

from ai_course_development_system.task_order import TASK_ORDER

RUNS_DIR = Path(__file__).parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)
RUNS: dict = {}

FIELDS = ["course_name", "level", "course_family", "course_id", "academy_constitution", "user_request"]

app = Flask(__name__)


def _save(run_id: str):
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(RUNS[run_id], default=str))


def _run_crew(run_id: str, inputs: dict):
    run = RUNS[run_id]
    try:
        from ai_course_development_system.crew import AiCourseDevelopmentSystemCrew
    except ImportError as e:
        run["status"] = f"error: crew engine not installed on this host ({e})"
        run["updated"] = datetime.now(timezone.utc).isoformat()
        _save(run_id)
        return
    try:
        crew = AiCourseDevelopmentSystemCrew().crew()
        by_name = {t.description: t for t in crew.tasks}

        def make_cb(task_name, agent_role):
            def _cb(output):
                run["outputs"][task_name] = {
                    "agent": agent_role,
                    "output": getattr(output, "raw", str(output)),
                }
                run["updated"] = datetime.now(timezone.utc).isoformat()
                _save(run_id)
            return _cb

        # Attach per-task callbacks for live debug updates (task order = TASK_ORDER).
        ordered_names = list(TASK_ORDER)
        for i, task in enumerate(crew.tasks):
            name = ordered_names[i] if i < len(ordered_names) else f"task_{i}"
            task.callback = make_cb(name, task.agent.role if task.agent else "?")
            run["outputs"].setdefault(name, {"agent": task.agent.role if task.agent else "?", "output": "(running…)"})

        result = crew.kickoff(inputs=inputs)
        for i, t_out in enumerate(result.tasks_output or []):
            name = ordered_names[i] if i < len(ordered_names) else f"task_{i}"
            run["outputs"][name] = {
                "agent": getattr(t_out, "agent", "?"),
                "output": t_out.raw,
            }
        run["status"] = "done"
    except Exception as e:  # noqa: BLE001 - surface to debug page
        run["status"] = f"error: {e}"
    run["updated"] = datetime.now(timezone.utc).isoformat()
    _save(run_id)


@app.get("/")
def index():
    items = "".join(
        f'<label>{f}<br><textarea name="{f}" rows={"5" if f == "user_request" else "1"} cols="70"></textarea></label><br><br>'
        for f in FIELDS
    )
    return f"""<h1>Course Automation — Prompt</h1>
<form method="post" action="/run">{items}<button type="submit">Run automation</button></form>
<p><a href="/runs">View all runs / debug outputs</a></p>"""


@app.post("/run")
def start_run():
    inputs = {f: request.form.get(f, "") for f in FIELDS}
    run_id = uuid.uuid4().hex[:8]
    RUNS[run_id] = {"id": run_id, "status": "running", "inputs": inputs,
                    "outputs": {}, "updated": datetime.now(timezone.utc).isoformat()}
    _save(run_id)
    threading.Thread(target=_run_crew, args=(run_id, inputs), daemon=True).start()
    return redirect(url_for("show_run", run_id=run_id))


@app.get("/runs")
def list_runs():
    rows = "".join(
        f'<li><a href="/runs/{r["id"]}">{r["id"]}</a> — {r["status"]} — {r["updated"]}</li>'
        for r in sorted(RUNS.values(), key=lambda r: r["updated"], reverse=True)
    ) or "<li>No runs yet. <a href='/'>Start one</a></li>"
    return f"<h1>Runs</h1><ul>{rows}</ul><p><a href='/'>Back to prompt</a></p>"


@app.get("/runs/<run_id>")
def show_run(run_id):
    run = RUNS.get(run_id)
    if run is None and (RUNS_DIR / f"{run_id}.json").exists():
        run = RUNS[run_id] = json.loads((RUNS_DIR / f"{run_id}.json").read_text())
    if run is None:
        return "Unknown run", 404
    refresh = '<meta http-equiv="refresh" content="5">' if run["status"] == "running" else ""
    blocks = ""
    for name in TASK_ORDER:
        o = run["outputs"].get(name, {"agent": "?", "output": "(pending…)"})
        blocks += f"<h3>{name} <small>({o['agent']})</small></h3><pre>{o['output']}</pre><hr>"
    return f"""{refresh}<h1>Run {run_id} — {run["status"]}</h1>
<p><a href="/">New prompt</a> | <a href="/runs">All runs</a></p>
<h2>Inputs</h2><pre>{json.dumps(run["inputs"], indent=2)}</pre><hr>
<h2>Per-agent outputs (debug)</h2>{blocks}"""


if __name__ == "__main__":
    app.run(debug=True, port=5000)
