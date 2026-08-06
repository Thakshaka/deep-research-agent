# Deep Research Agent

Automated pipeline that researches natural disaster events on the web using **Google Gemini** with **Google Search grounding**, then exports structured, source-backed CSV datasets.

## What it does

You provide a short list of disaster seeds (date, type, country, location). The script:

1. Researches each flagged event on the web
2. Extracts impact metrics into a fixed schema (deaths, evacuations, damage, etc.)
3. Collects source URLs used during research
4. Writes structured CSV outputs
5. On reruns, **keeps stable values** and only updates when there is a clear improvement

## Requirements

- Python 3.10+
- A [Gemini API key](https://aistudio.google.com/)

## Setup

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your-api-key-here
```

## Run

### GUI (recommended for lay users)

**Option A — Desktop app (most reliable)**

```bash
python gui.py
```

**Option B — Browser app (recommended on macOS)**

```bash
pip install flask
python web_gui.py
```

Open http://127.0.0.1:8080

**Option C — Streamlit (experimental on macOS)**

```bash
pip install streamlit
streamlit run app.py
```

Streamlit may segfault on some Macs when research runs. If you see `ERR_CONNECTION_REFUSED`, use Option A or B instead.

### Command line (batch CSV)

```bash
python main.py
```

The script reads `Source Sheet - Sheet1.csv` and writes output CSV files in the project folder.

## Input: Source Sheet

File: `Source Sheet - Sheet1.csv`

| Column   | Description                          |
|----------|--------------------------------------|
| Date     | Event date (`YYYY-MM-DD`)            |
| Disaster | Hazard type (e.g. Flash Flood)       |
| Country  | Country name                         |
| Location | City or region                       |
| Run      | `True` to process, `False` to skip   |

Example:

```csv
Date,Disaster,Country,Location,Run
2016-11-14,Earthquake,New Zealand,Culverden/Kaikoura (Canterbury province) / Wellington province,True
2026-04-20,Flash Flood,New Zealand,Wellington,False
```

Only rows with `Run=True` are researched. Accepted true values: `True`, `true`, `1`, `yes`, `y`.

Events with `Run=False` are skipped, but their existing output data is preserved if already present in the datasets.

## How processing works

For each event with `Run=True`:

```
Source row
   │
   ▼
Gemini + Google Search  ──►  Research summary + source URLs
   │
   ▼
Gemini (structured JSON) ──►  Event metrics (Pydantic schema)
   │
   ▼
Stable merge with previous snapshot (if exists)
   │
   ▼
Write / append CSV outputs
```

### Step 1: Web research

Gemini (`gemini-2.5-flash`) searches the web and returns a narrative summary of operational, human, and physical damage impacts. Source URLs are collected from Gemini grounding metadata.

### Step 2: Structured extraction

A second Gemini call maps the research text into a strict JSON schema (`EventExtract`), including fields like:

- `Event_ID`, `Event_Name`, `Hazard_Type`, `Start_Date`, `End_Date`
- `Deaths`, `Injured_Ill`, `Evacuated`
- `School_Closure_Duration`, `Dwellings_Damaged`, `Dwellings_Destroyed`
- `Infrastructure_Impact`, `Estimated_Damage_Cost`
- `Reliability_Weight`, `Confidence_Interval`

### Step 3: Stable merge (reruns)

On reruns, the script loads the previous `Dataset - Sheet1` row for each event and applies merge rules:

| Situation | Action |
|-----------|--------|
| Previous is `Unknown`, new is a real value | **Update** |
| Previous is known, new is `Unknown` | **Keep previous** |
| Both known but different (e.g. `>12` vs `>100`) | **Keep previous** |
| Death count increases | **Update** |
| New unique source URLs found | **Merge links**, update `Source_Count` |
| First run (no previous row) | **Accept all fields** |

History is appended **only when something actually changes**.

### Retries

API calls retry automatically on transient errors:

- Rate limits (`429`)
- Server overload (`503`)
- Network / SSL connection errors

## Output files

| File | Purpose |
|------|---------|
| `Dataset - Sheet1.csv` | Latest snapshot — one row per event |
| `Dataset - Sheet1 History.csv` | Append-only log of meaningful changes per run |
| `Dataset - Sources.csv` | `Event_ID` → `Source_Link` mapping |
| `Dataset - Source Lookup.csv` | Spreadsheet-friendly view: event block + source links |

### Sheet1 columns

Includes all extracted metrics plus:

- `Source_Count` — number of unique source URLs
- `Last_Updated_Run_Date` — date of the last meaningful update

### History behavior

- First run for an event creates a baseline history row
- Later runs append a row **only if fields changed**
- If a rerun finds no meaningful changes, history is not appended

Example timeline for one event:

| Run date | What changed |
|----------|----------------|
| Day 1 | All fields (initial baseline) |
| Day 2 | `Source_Count` only |
| Day 3 | `Estimated_Damage_Cost` (`Unknown` → estimate) + `Source_Count` |
| Day 4 | No changes — history skipped |

## Console output

During a run you may see messages like:

```
Loaded 2 event(s) from 'Source Sheet - Sheet1'.
Processing 1 event(s) with Run=True.
Skipping 1 event(s) with Run=False.

Grounding and researching: 'New Zealand Wellington Flash Flood on 2026-04-20'...
Retrieved 17 verified source URLs from the grounding metadata.
Updated fields for NZ-FLD-2026-04-20: Source_Count
Generated 'Dataset - Sheet1'
Appended 1 event(s) to 'Dataset - Sheet1 History'
```

Or, when nothing changed:

```
No meaningful changes for NZ-FLD-2026-04-20; kept previous values.
No meaningful changes; skipped append to 'Dataset - Sheet1 History'
```

## Limitations

- Output quality depends on publicly available web reporting at run time
- The model may return `Unknown` for fields with limited public data
- Stable merge prevents random field flipping on reruns, but does not verify official correctness
- Source links are grounding redirect URLs from Google, not always direct publisher URLs
- API usage is billed against your Gemini quota; grounding searches count toward usage

## Project structure

```
deep-research-agent/
├── main.py                      # Pipeline script
├── app.py                       # Streamlit web GUI (experimental on macOS)
├── web_gui.py                   # Flask browser GUI (recommended on macOS)
├── gui.py                       # Desktop GUI (Tkinter)
├── run_event.py                 # Isolated research runner for GUIs
├── Source Sheet - Sheet1.csv    # Input event list
├── Dataset - Sheet1.csv         # Latest output snapshot
├── Dataset - Sheet1 History.csv # Change history
├── Dataset - Sources.csv        # Event source links
├── Dataset - Source Lookup.csv  # Human-readable lookup layout
├── requirements.txt
├── .env                         # API key (not committed)
└── README.md
```
