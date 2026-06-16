"""Export applied jobs to CSV."""
import csv
from pathlib import Path

from job_agent.db.store import JobStore

CSV_PATH = Path("data/applications.csv")
_HEADERS = ["company", "job_title", "url", "applied_date", "tier", "score", "auto_mode", "resume"]


def export_csv(store: JobStore, output_path: Path = CSV_PATH) -> Path:
    """Write all applied jobs to a CSV file. Overwrites on each call."""
    rows = store.get_applied_jobs_with_apps()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "company":      row["company"],
                "job_title":    row["title"],
                "url":          row["url"],
                "applied_date": row["applied_at"][:10],   # YYYY-MM-DD
                "tier":         row.get("priority_tier", ""),
                "score":        f"{row['priority_score']:.2f}" if row.get("priority_score") else "",
                "auto_mode":    "yes" if row.get("auto_mode") else "no",
                "resume":       Path(row.get("resume_path", "")).name,
            })

    return output_path
