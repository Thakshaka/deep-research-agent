import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field

MODEL = "gemini-2.5-flash"
MAX_RETRIES = 6
INITIAL_RETRY_DELAY_SEC = 5
SOURCE_INPUT_PATH = "Source Sheet - Sheet1.csv"
SOURCE_RUN_COLUMN = "Run"
SHEET1_PATH = "Dataset - Sheet1.csv"
SHEET1_HISTORY_PATH = "Dataset - Sheet1 History.csv"
SOURCES_PATH = "Dataset - Sources.csv"
SOURCE_LOOKUP_PATH = "Dataset - Source Lookup.csv"


def dataset_label(path: str) -> str:
    return Path(path).stem


def parse_run_flag(value) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}

# =====================================================================
# 1. Define the Extraction Schema
# =====================================================================
class EventExtract(BaseModel):
    Event_ID: str = Field(description="Generate a unique identifier: CountryCode-DisasterAbbreviation-YYYY-MM-DD (e.g., 'NZ-FLD-2026-04-20')")
    Event_Name: str = Field(description="Formal event name, e.g., 'Wellington Flash Flood (April 2026)'")
    Hazard_Type: str = Field(description="Primary hazard sub-type")
    Start_Date: str = Field(description="Date the severe weather sequence began in YYYY-MM-DD format")
    End_Date: str = Field(description="Date the emergency state or impacts stabilized in YYYY-MM-DD format")
    Deaths: int = Field(description="Number of confirmed fatalities")
    Injured_Ill: str = Field(description="Reported injuries or public health illnesses")
    Evacuated: str = Field(description="Number or range of displaced/evacuated residents, e.g., '>100'")
    School_Closure_Duration: str = Field(description="Duration or scale of educational closures")
    Dwellings_Damaged: str = Field(description="Number of homes affected/damaged, e.g., '>100'")
    Dwellings_Destroyed: str = Field(description="Number of homes deemed uninhabitable or issued Dangerous Building Notices")
    Infrastructure_Impact: str = Field(description="Brief summary of transport, stormwater, and wastewater failures")
    Estimated_Damage_Cost: str = Field(description="Direct economic or insurance damage estimate")
    Reliability_Weight: str = Field(description="Score out of 10, e.g., '9/10'")
    Confidence_Interval: str = Field(description="Qualitative assessment of metrics confidence")


GOOGLE_SEARCH_TOOL = types.Tool(google_search=types.GoogleSearch())

SHEET1_COLUMNS = [
    "Event_ID",
    "Event_Name",
    "Hazard_Type",
    "Start_Date",
    "End_Date",
    "Deaths",
    "Injured_Ill",
    "Evacuated",
    "School_Closure_Duration",
    "Dwellings_Damaged",
    "Dwellings_Destroyed",
    "Infrastructure_Impact",
    "Estimated_Damage_Cost",
    "Reliability_Weight",
    "Confidence_Interval",
    "Source_Count",
    "Last_Updated_Run_Date",
]

MERGE_FIELDS = [
    field
    for field in SHEET1_COLUMNS
    if field not in ("Event_ID", "Source_Count", "Last_Updated_Run_Date")
]

UNKNOWN_MARKERS = {
    "",
    "unknown",
    "n/a",
    "na",
    "not available",
    "none",
    "unclear",
    "tbd",
    "not reported",
    "not specified",
}


def extract_grounding_links(response) -> list[str]:
    """Collect unique source URLs from Gemini grounding metadata."""
    unique_links: list[str] = []
    if not response.candidates:
        return unique_links

    metadata = response.candidates[0].grounding_metadata
    if metadata and metadata.grounding_chunks:
        for chunk in metadata.grounding_chunks:
            if chunk.web and chunk.web.uri:
                unique_links.append(chunk.web.uri)

    return sorted(set(unique_links))


def _should_retry_api_call(exc: Exception, attempt: int) -> tuple[bool, str]:
    if attempt >= MAX_RETRIES:
        return False, ""

    if isinstance(exc, (genai_errors.ServerError, genai_errors.ClientError)):
        if exc.code in (429, 503):
            return True, f"API {exc.code} ({exc.status or 'UNAVAILABLE'})"
        return False, ""

    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True, f"connection error ({exc.__class__.__name__})"

    return False, ""


def generate_with_retry(client: genai.Client, *, contents, config) -> object:
    """Call Gemini with retries on transient API, network, or SSL errors."""
    delay = INITIAL_RETRY_DELAY_SEC
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            last_error = exc
            should_retry, reason = _should_retry_api_call(exc, attempt)
            if not should_retry:
                raise
            print(
                f"Warning: {reason}, retrying in {delay}s ({attempt}/{MAX_RETRIES})...",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay = min(delay * 2, 60)

    raise last_error  # pragma: no cover


def is_unknown(value) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in UNKNOWN_MARKERS:
            return True
        if normalized.startswith("unknown"):
            return True
        if "no widespread reports" in normalized or "numbers unknown" in normalized:
            return True
    return False


def normalize_value(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def should_update_field(field_name: str, previous, new) -> bool:
    previous = normalize_value(previous)
    new = normalize_value(new)

    if field_name == "Deaths":
        previous_deaths = int(previous) if str(previous).isdigit() else 0
        new_deaths = int(new) if str(new).isdigit() else 0
        return new_deaths > previous_deaths

    if is_unknown(previous) and not is_unknown(new):
        return True
    if not is_unknown(previous) and is_unknown(new):
        return False
    if str(previous).strip().lower() == str(new).strip().lower():
        return False

    # Both values are known but different: keep the existing stable value.
    return False


def load_previous_sheet1() -> dict[str, dict]:
    if not Path(SHEET1_PATH).exists():
        return {}

    df = pd.read_csv(SHEET1_PATH)
    records: dict[str, dict] = {}
    for _, row in df.iterrows():
        record = {col: normalize_value(row.get(col, "")) for col in SHEET1_COLUMNS}
        if str(record.get("Deaths", "")).isdigit():
            record["Deaths"] = int(record["Deaths"])
        if str(record.get("Source_Count", "")).isdigit():
            record["Source_Count"] = int(record["Source_Count"])
        records[str(record["Event_ID"])] = record
    return records


def load_previous_sources() -> dict[str, list[str]]:
    if not Path(SOURCES_PATH).exists():
        return {}

    df = pd.read_csv(SOURCES_PATH)
    records: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        event_id = str(row["Event_ID"])
        records.setdefault(event_id, []).append(str(row["Source_Link"]))
    return {event_id: sorted(set(links)) for event_id, links in records.items()}


def merge_event_record(
    previous: dict | None,
    incoming: dict,
    merged_links: list[str],
    run_date: str,
) -> tuple[dict, list[str]]:
    if not previous:
        merged = incoming.copy()
        merged["Source_Count"] = len(merged_links)
        merged["Last_Updated_Run_Date"] = run_date
        return merged, MERGE_FIELDS.copy()

    merged = previous.copy()
    changed_fields: list[str] = []

    for field in MERGE_FIELDS:
        if should_update_field(field, previous.get(field), incoming.get(field)):
            merged[field] = incoming[field]
            changed_fields.append(field)

    if len(merged_links) > int(previous.get("Source_Count", 0) or 0):
        changed_fields.append("Source_Count")

    merged["Source_Count"] = len(merged_links)
    if changed_fields:
        merged["Last_Updated_Run_Date"] = run_date
    else:
        merged["Last_Updated_Run_Date"] = previous.get("Last_Updated_Run_Date", run_date)

    return merged, changed_fields


# =====================================================================
# 2. Main Processing Function
# =====================================================================
def process_natural_disasters(source_csv_path: str):
    load_dotenv(Path(__file__).resolve().parent / ".env")

    if not os.environ.get("GEMINI_API_KEY"):
        print("Error: Set GEMINI_API_KEY in .env or the environment.", file=sys.stderr)
        sys.exit(1)

    client = genai.Client()
    run_date = datetime.now().date().isoformat()

    df_source = pd.read_csv(source_csv_path)
    total_events = len(df_source)
    print(f"Loaded {total_events} event(s) from '{dataset_label(source_csv_path)}'.")

    if SOURCE_RUN_COLUMN not in df_source.columns:
        print(
            f"Error: '{SOURCE_RUN_COLUMN}' column is required in "
            f"'{dataset_label(source_csv_path)}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    df_to_run = df_source[df_source[SOURCE_RUN_COLUMN].apply(parse_run_flag)]
    skipped_events = total_events - len(df_to_run)
    print(f"Processing {len(df_to_run)} event(s) with {SOURCE_RUN_COLUMN}=True.")
    if skipped_events:
        print(f"Skipping {skipped_events} event(s) with {SOURCE_RUN_COLUMN}=False.")

    previous_sheet1 = load_previous_sheet1()
    previous_sources = load_previous_sources()

    sheet1_records: list[dict] = []
    sources_records: list[dict] = []
    history_records: list[dict] = []
    processed_event_ids: set[str] = set()

    for _, row in df_to_run.iterrows():
        date = row["Date"]
        disaster = row["Disaster"]
        country = row["Country"]
        location = row["Location"]

        search_query = f"{country} {location} {disaster} on {date}"
        print(f"\nGrounding and researching: '{search_query}'...")

        research_response = generate_with_retry(
            client,
            contents=(
                "Conduct deep research and extract full operational, human, "
                f"and physical damage metrics for: {search_query}"
            ),
            config=types.GenerateContentConfig(
                tools=[GOOGLE_SEARCH_TOOL],
                temperature=0.0,
            ),
        )

        unique_links = extract_grounding_links(research_response)
        source_count = len(unique_links)
        print(f"Retrieved {source_count} verified source URLs from the grounding metadata.")

        extraction_prompt = (
            "Map the following research details to the schema. "
            "Use only information supported by the research. "
            "If a field is unknown, use a clear placeholder such as 'Unknown'.\n\n"
            f"{research_response.text}"
        )
        structured_response = generate_with_retry(
            client,
            contents=extraction_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=EventExtract,
                temperature=0.0,
            ),
        )

        extracted_data = EventExtract.model_validate_json(structured_response.text)
        incoming_record = extracted_data.model_dump()
        event_id = str(incoming_record["Event_ID"])

        merged_links = sorted(set(previous_sources.get(event_id, [])) | set(unique_links))
        merged_record, changed_fields = merge_event_record(
            previous_sheet1.get(event_id),
            incoming_record,
            merged_links,
            run_date,
        )
        sheet1_records.append(merged_record)
        processed_event_ids.add(event_id)

        if changed_fields:
            print(f"Updated fields for {event_id}: {', '.join(changed_fields)}")
            history_records.append(merged_record)
        else:
            print(f"No meaningful changes for {event_id}; kept previous values.")

        for link in merged_links:
            sources_records.append({"Event_ID": event_id, "Source_Link": link})

    # Keep unprocessed events from the previous snapshot.
    for event_id, previous_record in previous_sheet1.items():
        if event_id not in processed_event_ids:
            sheet1_records.append(previous_record)

    for event_id, links in previous_sources.items():
        if event_id not in processed_event_ids:
            for link in links:
                sources_records.append({"Event_ID": event_id, "Source_Link": link})

    # =====================================================================
    # 3. Write results to local relational CSV tables
    # =====================================================================
    df_sheet1 = pd.DataFrame(sheet1_records, columns=SHEET1_COLUMNS)
    df_sheet1.to_csv(SHEET1_PATH, index=False)
    print(f"Generated '{dataset_label(SHEET1_PATH)}'")

    if history_records:
        df_history = pd.DataFrame(history_records, columns=SHEET1_COLUMNS)
        df_history.insert(0, "Run_Date", run_date)
        history_exists = Path(SHEET1_HISTORY_PATH).exists()
        df_history.to_csv(
            SHEET1_HISTORY_PATH,
            mode="a",
            index=False,
            header=not history_exists,
        )
        print(
            f"Appended {len(history_records)} event(s) to "
            f"'{dataset_label(SHEET1_HISTORY_PATH)}'"
        )
    else:
        print(
            f"No meaningful changes; skipped append to "
            f"'{dataset_label(SHEET1_HISTORY_PATH)}'"
        )

    df_sources = pd.DataFrame(sources_records)
    df_sources.to_csv(SOURCES_PATH, index=False)
    print(f"Generated '{dataset_label(SOURCES_PATH)}'")

    generate_lookup_dashboard(sheet1_records, sources_records)


# =====================================================================
# 4. Helper to build the interactive lookup dashboard
# =====================================================================
def generate_lookup_dashboard(sheet1_records: list[dict], sources_records: list[dict]):
    """Write a spreadsheet-friendly block per event: metrics, then source links."""
    with open(SOURCE_LOOKUP_PATH, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        for event in sheet1_records:
            e_id = event["Event_ID"]
            count = event.get("Source_Count", 0)

            writer.writerow(SHEET1_COLUMNS)
            writer.writerow([event.get(col, "") for col in SHEET1_COLUMNS])
            writer.writerow([])
            writer.writerow(["Event_ID", e_id, "Source_Count", count])
            writer.writerow(["Source_Link"])

            for mapping in sources_records:
                if mapping["Event_ID"] == e_id:
                    writer.writerow([mapping["Source_Link"]])

            writer.writerow([])

    print(f"Generated '{dataset_label(SOURCE_LOOKUP_PATH)}'")


if __name__ == "__main__":
    process_natural_disasters(SOURCE_INPUT_PATH)
