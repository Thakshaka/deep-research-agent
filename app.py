"""Streamlit GUI (experimental on macOS — prefer web_gui.py or gui.py)."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

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

st.set_page_config(page_title="Deep Research Agent", layout="wide")

st.title("Deep Research Agent")
st.warning(
    "Streamlit can crash on some Macs. If you see connection errors, use "
    "`python web_gui.py` or `python gui.py` instead.",
)

load_dotenv(PROJECT_DIR / ".env")
if not os.environ.get("GEMINI_API_KEY"):
    st.error("Add your `GEMINI_API_KEY` to a `.env` file in the project folder, then refresh this page.")
    st.stop()


def run_research_subprocess(
    *,
    disaster: str,
    country: str,
    location: str,
    year: int,
    month: int | None,
    day: int | None,
) -> dict:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as handle:
        output_path = handle.name

    command = [
        sys.executable,
        str(PROJECT_DIR / "run_event.py"),
        "--disaster",
        disaster,
        "--country",
        country,
        "--location",
        location,
        "--year",
        str(year),
        "--output",
        output_path,
    ]
    if month is not None and day is not None:
        command.extend(["--month", str(month), "--day", str(day)])

    completed = subprocess.run(command, cwd=PROJECT_DIR, capture_output=True, text=True)

    try:
        payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
    finally:
        Path(output_path).unlink(missing_ok=True)

    if completed.returncode in (-11, 139):
        raise RuntimeError(
            "Research process crashed. Use `python web_gui.py` or `python gui.py` instead."
        )
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or completed.stderr or "Research failed.")

    return payload


st.write(
    "Enter a disaster event and the agent will search the web, "
    "extract impact details, and save a structured record with sources."
)

st.subheader("Event details")
event_name = st.text_input("Event name", placeholder="Flash Flood")
location = st.text_input("Location", placeholder="Wellington")
country = st.text_input("Country", placeholder="New Zealand")
year = st.number_input("Year", min_value=1900, max_value=2100, value=2024, step=1)

use_exact_date = st.checkbox("I know the month and day")
month = day = None
if use_exact_date:
    col_month, col_day = st.columns(2)
    with col_month:
        month = st.number_input("Month", min_value=1, max_value=12, value=1)
    with col_day:
        day = st.number_input("Day", min_value=1, max_value=31, value=1)

run_research = st.button("Run research", type="primary")

if run_research:
    missing = [
        label
        for label, value in [
            ("Event name", event_name),
            ("Location", location),
            ("Country", country),
        ]
        if not str(value).strip()
    ]
    if missing:
        st.error(f"Please fill in: {', '.join(missing)}")
    else:
        with st.status("Researching event...", expanded=True) as status:
            try:
                payload = run_research_subprocess(
                    disaster=event_name.strip(),
                    country=country.strip(),
                    location=location.strip(),
                    year=int(year),
                    month=int(month) if use_exact_date and month else None,
                    day=int(day) if use_exact_date and day else None,
                )
                status.update(label="Research complete", state="complete")
            except Exception as exc:
                status.update(label="Research failed", state="error")
                st.error(str(exc))
                st.stop()

        for line in payload.get("logs", []):
            st.write(line)

        record = payload["record"]
        st.success(f"Finished research for **{payload['event_id']}**")

        if payload.get("changed_fields"):
            st.info("Updated fields: " + ", ".join(payload["changed_fields"]))
        else:
            st.info("No meaningful changes — kept the previous record.")

        st.subheader("Results")
        st.table(
            [{"Field": label, "Value": record.get(key, "")} for label, key in DISPLAY_FIELDS]
        )

        st.subheader("Sources")
        if payload.get("sources"):
            for index, link in enumerate(payload["sources"], start=1):
                st.markdown(f"{index}. [{link}]({link})")
        else:
            st.write("No source links were returned for this run.")

        with st.expander("Search query used"):
            st.code(payload["search_query"])

st.divider()
st.caption(
    "Results are saved to the project datasets (Sheet1, History, Sources, and Source Lookup)."
)
