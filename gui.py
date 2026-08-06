"""Desktop GUI for the Deep Research Agent (no browser required)."""

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

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


class DeepResearchGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Deep Research Agent")
        self.root.geometry("900x700")
        self._build_form()
        self._check_api_key()

    def _build_form(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Deep Research Agent",
            font=("Helvetica", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="Enter event details and run web research to build a structured record.",
        ).pack(anchor="w", pady=(0, 12))

        form = ttk.LabelFrame(frame, text="Event details", padding=12)
        form.pack(fill="x", pady=(0, 12))

        self.event_name = tk.StringVar()
        self.location = tk.StringVar()
        self.country = tk.StringVar(value="New Zealand")
        self.year = tk.StringVar(value="2024")
        self.use_exact_date = tk.BooleanVar(value=False)
        self.month = tk.StringVar(value="1")
        self.day = tk.StringVar(value="1")

        self._add_field(form, "Event name", self.event_name, "e.g. Flash Flood")
        self._add_field(form, "Location", self.location, "e.g. Wellington")
        self._add_field(form, "Country", self.country, "e.g. New Zealand")
        self._add_field(form, "Year", self.year, "e.g. 2024")

        exact_row = ttk.Frame(form)
        exact_row.pack(fill="x", pady=4)
        ttk.Checkbutton(
            exact_row,
            text="I know the month and day",
            variable=self.use_exact_date,
            command=self._toggle_exact_date,
        ).pack(anchor="w")

        self.date_frame = ttk.Frame(form)
        self.date_frame.pack(fill="x", pady=4)
        ttk.Label(self.date_frame, text="Month", width=14).pack(side="left")
        ttk.Entry(self.date_frame, textvariable=self.month, width=8).pack(side="left", padx=(0, 12))
        ttk.Label(self.date_frame, text="Day", width=6).pack(side="left")
        ttk.Entry(self.date_frame, textvariable=self.day, width=8).pack(side="left")
        self._toggle_exact_date()

        self.run_button = ttk.Button(frame, text="Run research", command=self._start_research)
        self.run_button.pack(anchor="w", pady=(0, 12))

        ttk.Label(frame, text="Status").pack(anchor="w")
        self.status = scrolledtext.ScrolledText(frame, height=8, wrap="word")
        self.status.pack(fill="x", pady=(4, 12))
        self.status.configure(state="disabled")

        ttk.Label(frame, text="Results").pack(anchor="w")
        self.results = scrolledtext.ScrolledText(frame, height=18, wrap="word")
        self.results.pack(fill="both", expand=True, pady=(4, 0))
        self.results.configure(state="disabled")

    def _add_field(
        self,
        parent: ttk.LabelFrame,
        label: str,
        variable: tk.StringVar,
        placeholder: str,
    ) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=14).pack(side="left")
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Label(row, text=placeholder, foreground="gray").pack(side="left", padx=(8, 0))

    def _toggle_exact_date(self) -> None:
        state = "normal" if self.use_exact_date.get() else "disabled"
        for child in self.date_frame.winfo_children():
            if isinstance(child, ttk.Entry):
                child.configure(state=state)

    def _check_api_key(self) -> None:
        try:
            from main import ensure_api_key

            ensure_api_key()
        except ValueError as exc:
            messagebox.showerror("Missing API key", str(exc))

    def _append_text(self, widget: scrolledtext.ScrolledText, text: str) -> None:
        widget.configure(state="normal")
        widget.insert("end", text + "\n")
        widget.see("end")
        widget.configure(state="disabled")

    def _clear_text(self, widget: scrolledtext.ScrolledText) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")

    def _start_research(self) -> None:
        if not self.event_name.get().strip():
            messagebox.showwarning("Missing input", "Please enter an event name.")
            return
        if not self.location.get().strip():
            messagebox.showwarning("Missing input", "Please enter a location.")
            return
        if not self.country.get().strip():
            messagebox.showwarning("Missing input", "Please enter a country.")
            return
        if not self.year.get().strip().isdigit():
            messagebox.showwarning("Invalid year", "Please enter a valid year.")
            return

        self.run_button.configure(state="disabled")
        self._clear_text(self.status)
        self._clear_text(self.results)
        self._append_text(self.status, "Starting research...")

        thread = threading.Thread(target=self._run_research, daemon=True)
        thread.start()

    def _run_research(self) -> None:
        from main import process_single_event

        logs: list[str] = []

        def capture_log(message: str) -> None:
            logs.append(message)
            self.root.after(0, self._append_text, self.status, message)

        try:
            month = int(self.month.get()) if self.use_exact_date.get() else None
            day = int(self.day.get()) if self.use_exact_date.get() else None
            result = process_single_event(
                disaster=self.event_name.get().strip(),
                country=self.country.get().strip(),
                location=self.location.get().strip(),
                year=int(self.year.get().strip()),
                month=month,
                day=day,
                log=capture_log,
            )
        except Exception as exc:
            self.root.after(0, self._on_error, str(exc))
            return

        self.root.after(0, self._on_success, result)

    def _on_error(self, message: str) -> None:
        self._append_text(self.status, f"Error: {message}")
        messagebox.showerror("Research failed", message)
        self.run_button.configure(state="normal")

    def _on_success(self, result: dict) -> None:
        record = result["record"]
        lines = [
            f"Finished: {result['event_id']}",
            f"Search query: {result['search_query']}",
            "",
        ]

        if result["changed_fields"]:
            lines.append("Updated fields: " + ", ".join(result["changed_fields"]))
        else:
            lines.append("No meaningful changes — kept the previous record.")

        lines.append("")
        for label, key in DISPLAY_FIELDS:
            lines.append(f"{label}: {record.get(key, '')}")

        lines.append("")
        lines.append("Sources:")
        if result["sources"]:
            for index, link in enumerate(result["sources"], start=1):
                lines.append(f"{index}. {link}")
        else:
            lines.append("No source links were returned.")

        self._append_text(self.results, "\n".join(lines))
        self._append_text(self.status, "Research complete.")
        self.run_button.configure(state="normal")


def main() -> None:
    root = tk.Tk()
    DeepResearchGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
