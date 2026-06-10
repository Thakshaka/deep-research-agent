# Deep Research Agent

## What is this?

The **Deep Research Agent** is a tool that helps build structured disaster-impact records automatically.

You start with a short list of events — for example, a flash flood in Wellington on a given date. The agent researches what happened using publicly available information on the web, then organises the findings into a consistent dataset with source links.

It is designed for work like tracking natural disaster impacts: deaths, injuries, evacuations, damage to homes and infrastructure, school closures, and estimated costs.

Instead of manually searching and copying information into spreadsheets, you run the agent and it produces ready-to-use outputs that can be reviewed, shared, and updated over time.

---

## How does it work?

### 1. You provide a list of events

You keep a simple input list with basic details for each event:

- When it happened
- What type of disaster it was
- Where it happened (country and location)

Each event also has a **Run** flag. Only events marked to run are researched in that session. This lets you choose which events to process without removing others from your list.

### 2. The agent researches each selected event

For every event you choose to run, the agent:

- Searches the web for reports and articles about that disaster
- Reads and combines information from multiple sources
- Summarises what it finds about human, operational, and physical impacts

### 3. Findings are organised into a standard format

The agent turns the research into a structured record with the same fields every time, such as:

- Event name and hazard type
- Start and end dates
- Deaths, injuries, and evacuations
- Damage to homes and infrastructure
- School closures
- Estimated damage cost
- A reliability / confidence note

This makes different events easier to compare in one table.

### 4. Sources are saved alongside the data

For each event, the agent also keeps a list of the web sources it used. That way, each record can be checked against original reporting.

### 5. Outputs are saved as datasets

After a run, you get:

- **A current snapshot** — the latest version of each event’s record
- **A history log** — a record of meaningful changes over time
- **A source list** — links tied to each event
- **A lookup view** — an easy-to-read layout for reviewing an event and its sources together

### 6. Reruns improve data without losing stability

You can run the agent again on later days as more information becomes available.

On reruns, it does **not** randomly rewrite everything. It keeps existing values unless something clearly improves, for example:

- A field that was previously unknown now has a reported value
- A death count increases as official numbers are updated
- Additional source links are found

If nothing meaningful has changed, the current record stays the same and no unnecessary history entry is added.

---

## What is it useful for?

- Building disaster impact datasets faster than manual research
- Keeping a consistent structure across many events
- Tracking how reported impacts change over time
- Maintaining source links for verification and review

---

## What to keep in mind

- The agent depends on what is publicly reported online at the time of each run
- Outputs should be reviewed — especially for critical fields like fatalities and damage figures
- It supports research and data collection; it is not a replacement for official verified records
