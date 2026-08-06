"""Lightweight browser GUI (Flask). Use this instead of Streamlit on macOS."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, render_template_string, request, url_for

PROJECT_DIR = Path(__file__).resolve().parent
DISPLAY_FIELDS = [
    ("Event ID", "Event_ID"),
    ("Event name", "Event_Name"),
    ("Hazard type", "Hazard_Type"),
    ("Start date", "Start_Date"),
    ("End date", "End_Date"),
    ("Deaths", "Deaths"),
    ("Injured / ill", "Injured_Ill"),
    ("Evacuated", "Evacuated"),
    ("School closures", "School_Closure_Duration"),
    ("Dwellings damaged", "Dwellings_Damaged"),
    ("Dwellings destroyed", "Dwellings_Destroyed"),
    ("Infrastructure impact", "Infrastructure_Impact"),
    ("Estimated damage cost", "Estimated_Damage_Cost"),
    ("Reliability", "Reliability_Weight"),
    ("Confidence", "Confidence_Interval"),
    ("Source count", "Source_Count"),
    ("Last updated", "Last_Updated_Run_Date"),
]

PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Deep Research Agent</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; background: #f6f7fb; color: #1f2937; }
    .wrap { max-width: 900px; margin: 0 auto; padding: 32px 20px 48px; }
    h1 { margin-bottom: 8px; }
    .card { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 10px rgba(0,0,0,.06); margin-top: 20px; }
    label { display: block; font-weight: 600; margin: 14px 0 6px; }
    input[type=text], input[type=number] { width: 100%; padding: 10px 12px; border: 1px solid #d1d5db; border-radius: 8px; box-sizing: border-box; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    button { margin-top: 20px; background: #2563eb; color: white; border: 0; border-radius: 8px; padding: 12px 18px; font-size: 16px; cursor: pointer; }
    button:hover { background: #1d4ed8; }
    .error { background: #fee2e2; color: #991b1b; padding: 12px; border-radius: 8px; }
    .success { background: #dcfce7; color: #166534; padding: 12px; border-radius: 8px; }
    .info { background: #dbeafe; color: #1e40af; padding: 12px; border-radius: 8px; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
    th { width: 220px; color: #4b5563; }
    pre, .logs { white-space: pre-wrap; background: #111827; color: #e5e7eb; padding: 12px; border-radius: 8px; font-size: 13px; }
    a { color: #2563eb; word-break: break-all; }
    .hint { color: #6b7280; font-size: 14px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Deep Research Agent</h1>
    <p class="hint">Enter event details, run web research, and save a structured disaster record with sources.</p>

    {% if api_error %}
    <div class="card error">{{ api_error }}</div>
    {% endif %}

    <div class="card">
      <form method="post">
        <label for="disaster">Event name</label>
        <input id="disaster" name="disaster" type="text" placeholder="Flash Flood" value="{{ form.disaster }}" required>

        <label for="location">Location</label>
        <input id="location" name="location" type="text" placeholder="Wellington" value="{{ form.location }}" required>

        <label for="country">Country</label>
        <input id="country" name="country" type="text" placeholder="New Zealand" value="{{ form.country }}" required>

        <label for="year">Year</label>
        <input id="year" name="year" type="number" min="1900" max="2100" value="{{ form.year }}" required>

        <label><input type="checkbox" name="use_exact_date" {% if form.use_exact_date %}checked{% endif %}> I know the month and day</label>

        <div class="row">
          <div>
            <label for="month">Month</label>
            <input id="month" name="month" type="number" min="1" max="12" value="{{ form.month }}">
          </div>
          <div>
            <label for="day">Day</label>
            <input id="day" name="day" type="number" min="1" max="31" value="{{ form.day }}">
          </div>
        </div>

        <button type="submit">Run research</button>
      </form>
    </div>

    {% if error %}
    <div class="card error">{{ error }}</div>
    {% endif %}

    {% if result %}
    <div class="card success">Finished research for <strong>{{ result.event_id }}</strong></div>
    <div class="card info">{{ result.summary }}</div>

    <div class="card">
      <h2>Results</h2>
      <table>
        {% for label, value in result.rows %}
        <tr><th>{{ label }}</th><td>{{ value }}</td></tr>
        {% endfor %}
      </table>
    </div>

    <div class="card">
      <h2>Sources</h2>
      {% if result.sources %}
      <ol>
        {% for link in result.sources %}
        <li><a href="{{ link }}" target="_blank" rel="noopener">{{ link }}</a></li>
        {% endfor %}
      </ol>
      {% else %}
      <p>No source links were returned.</p>
      {% endif %}
    </div>

    <div class="card">
      <h2>Search query used</h2>
      <pre>{{ result.search_query }}</pre>
    </div>

    {% if result.logs %}
    <div class="card">
      <h2>Status log</h2>
      <div class="logs">{{ result.logs }}</div>
    </div>
    {% endif %}
    {% endif %}

    <p class="hint">Results are saved to the project datasets (Sheet1, History, Sources, and Source Lookup).</p>
  </div>
</body>
</html>
"""

app = Flask(__name__)


def _api_key_error() -> str | None:
    load_dotenv(PROJECT_DIR / ".env")
    if not os.environ.get("GEMINI_API_KEY"):
        return "Add GEMINI_API_KEY to a .env file in the project folder, then restart the server."
    return None


def _default_form() -> dict:
    return {
        "disaster": "",
        "location": "",
        "country": "New Zealand",
        "year": "2024",
        "use_exact_date": False,
        "month": "1",
        "day": "1",
    }


def _run_research(form: dict) -> dict:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as handle:
        output_path = handle.name

    command = [
        sys.executable,
        str(PROJECT_DIR / "run_event.py"),
        "--disaster",
        form["disaster"],
        "--country",
        form["country"],
        "--location",
        form["location"],
        "--year",
        str(form["year"]),
        "--output",
        output_path,
    ]
    if form.get("use_exact_date"):
        command.extend(["--month", str(form["month"]), "--day", str(form["day"])])

    completed = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )

    try:
        payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
    finally:
        Path(output_path).unlink(missing_ok=True)

    if completed.returncode != 0 and not payload.get("ok"):
        if completed.returncode in (-11, 139) or "Segmentation fault" in (completed.stderr or ""):
            raise RuntimeError(
                "The research process crashed on this machine. Try the desktop app: python gui.py"
            )
        raise RuntimeError(payload.get("error") or completed.stderr or "Research failed.")

    if not payload.get("ok"):
        raise RuntimeError(payload.get("error", "Research failed."))

    record = payload["record"]
    rows = [(label, escape(str(record.get(key, "")))) for label, key in DISPLAY_FIELDS]
    if payload.get("changed_fields"):
        summary = "Updated fields: " + ", ".join(payload["changed_fields"])
    else:
        summary = "No meaningful changes — kept the previous record."

    return {
        "event_id": escape(payload["event_id"]),
        "search_query": escape(payload["search_query"]),
        "summary": escape(summary),
        "rows": rows,
        "sources": payload.get("sources", []),
        "logs": escape("\n".join(payload.get("logs", []))),
    }


@app.route("/", methods=["GET", "POST"])
def index():
    api_error = _api_key_error()
    form = _default_form()
    error = None
    result = None

    if request.method == "POST":
        form = {
            "disaster": request.form.get("disaster", "").strip(),
            "location": request.form.get("location", "").strip(),
            "country": request.form.get("country", "").strip(),
            "year": request.form.get("year", "").strip(),
            "use_exact_date": request.form.get("use_exact_date") == "on",
            "month": request.form.get("month", "1").strip(),
            "day": request.form.get("day", "1").strip(),
        }

        if not form["disaster"] or not form["location"] or not form["country"]:
            error = "Please fill in event name, location, and country."
        elif not form["year"].isdigit():
            error = "Please enter a valid year."
        elif api_error:
            error = api_error
        else:
            try:
                result = _run_research(form)
            except Exception as exc:
                error = str(exc)

    return render_template_string(
        PAGE,
        api_error=api_error,
        form=form,
        error=error,
        result=result,
    )


if __name__ == "__main__":
    print("Open http://127.0.0.1:8080 in your browser")
    app.run(host="127.0.0.1", port=8080, debug=False)
