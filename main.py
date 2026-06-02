import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

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
SHEET1_PATH = "Dataset - Sheet1.csv"
SHEET1_HISTORY_PATH = "Dataset - Sheet1 History.csv"
SOURCES_PATH = "Dataset - Sources.csv"
SOURCE_LOOKUP_PATH = "Dataset - Source Lookup.csv"


def dataset_label(path: str) -> str:
    return Path(path).stem

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


def generate_with_retry(client: genai.Client, *, contents, config) -> object:
    """Call Gemini with retries on transient overload (503) or rate limits (429)."""
    delay = INITIAL_RETRY_DELAY_SEC
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=config,
            )
        except (genai_errors.ServerError, genai_errors.ClientError) as exc:
            last_error = exc
            if exc.code not in (429, 503) or attempt == MAX_RETRIES:
                raise
            print(
                f"Warning: API {exc.code} ({exc.status or 'UNAVAILABLE'}), "
                f"retrying in {delay}s ({attempt}/{MAX_RETRIES})...",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay = min(delay * 2, 60)

    raise last_error  # pragma: no cover


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
    print(f"Loaded {len(df_source)} event(s) from '{dataset_label(source_csv_path)}'.")

    sheet1_records: list[dict] = []
    sources_records: list[dict] = []

    for _, row in df_source.iterrows():
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
            config=types.GenerateContentConfig(tools=[GOOGLE_SEARCH_TOOL]),
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
        data_dict = extracted_data.model_dump()
        data_dict["Source_Count"] = source_count
        data_dict["Last_Updated_Run_Date"] = run_date
        sheet1_records.append(data_dict)

        event_id = data_dict["Event_ID"]
        for link in unique_links:
            sources_records.append({"Event_ID": event_id, "Source_Link": link})

    # =====================================================================
    # 3. Write results to local relational CSV tables
    # =====================================================================
    df_sheet1 = pd.DataFrame(sheet1_records, columns=SHEET1_COLUMNS)
    df_sheet1.to_csv(SHEET1_PATH, index=False)
    print(f"Generated '{dataset_label(SHEET1_PATH)}'")

    # Append snapshot rows to run history (append-only).
    df_history = df_sheet1.copy()
    df_history.insert(0, "Run_Date", run_date)
    history_exists = Path(SHEET1_HISTORY_PATH).exists()
    df_history.to_csv(
        SHEET1_HISTORY_PATH,
        mode="a",
        index=False,
        header=not history_exists,
    )
    print(f"Appended '{dataset_label(SHEET1_HISTORY_PATH)}'")

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
