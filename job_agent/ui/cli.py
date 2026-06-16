"""Rich-based interactive CLI for reviewing and applying to jobs."""
import sys
from pathlib import Path
from typing import Optional

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from job_agent.ai.client import session_token_counts
from job_agent.db.models import Job
from job_agent.db.store import JobStore

console = Console()

TIER_COLORS = {
    1: "bright_green",
    2: "green",
    3: "yellow",
    4: "white",
}

TIER_LABELS = {
    1: "C++ / Systems",
    2: "Low-level / Infra",
    3: "Graphics / GPU",
    4: "General SWE",
}


def render_job_panel(
    job: Job,
    index: int,
    total: int,
    resume_path: Optional[Path] = None,
    cover_letter: Optional[str] = None,
) -> Panel:
    """Render a single job as a Rich panel."""
    tier_color = TIER_COLORS.get(job.priority_tier or 4, "white")
    tier_label = TIER_LABELS.get(job.priority_tier or 4, "Unknown")

    # Header
    title_text = Text()
    title_text.append(f"[{index}/{total}] ", style="dim")
    title_text.append(job.title, style=f"bold {tier_color}")
    title_text.append(f"  @  ", style="dim")
    title_text.append(job.company, style="bold cyan")

    lines = [
        title_text,
        Text.from_markup(
            f"[dim]Location:[/dim] {job.location or 'N/A'}  |  "
            f"[dim]Source:[/dim] {job.source}  |  "
            f"[dim]ATS:[/dim] {job.ats_type or 'unknown'}"
        ),
        Text.from_markup(
            f"[dim]Tier:[/dim] [{tier_color}]{job.priority_tier} — {tier_label}[/{tier_color}]  |  "
            f"[dim]Score:[/dim] {job.priority_score:.2f}" if job.priority_score else
            f"[dim]Tier:[/dim] [{tier_color}]{job.priority_tier} — {tier_label}[/{tier_color}]"
        ),
    ]

    if job.priority_reason:
        lines.append(Text.from_markup(f"[dim]Reason:[/dim] {job.priority_reason}"))

    if resume_path:
        lines.append(Text.from_markup(f"[dim]Resume:[/dim] [blue]{resume_path.name}[/blue]"))

    if job.url:
        lines.append(Text.from_markup(f"[dim]URL:[/dim] [link={job.url}]{job.url[:80]}[/link]"))

    if cover_letter:
        cl_preview = cover_letter[:200].replace("\n", " ") + ("…" if len(cover_letter) > 200 else "")
        lines.append(Text())
        lines.append(Text.from_markup(f"[dim]Cover letter preview:[/dim]\n[italic]{cl_preview}[/italic]"))

    lines.append(Text())
    lines.append(Text.from_markup(
        "  [bold green][a][/bold green] Apply  "
        "  [bold yellow][s][/bold yellow] Skip  "
        "  [bold magenta][A][/bold magenta] Auto-apply rest  "
        "  [bold blue][v][/bold blue] View description  "
        "  [bold red][q][/bold red] Quit"
    ))

    body = "\n".join(str(line) for line in lines)
    return Panel(
        "\n".join(str(l) for l in lines),
        border_style=tier_color,
        padding=(0, 1),
    )


def print_stats(store: JobStore) -> None:
    stats = store.stats()
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_row("[dim]Total[/dim]", str(stats.get("total", 0)))
    table.add_row("[green]Applied[/green]", str(stats.get("applied", 0)))
    table.add_row("[yellow]Pending[/yellow]", str(stats.get("pending", 0)))
    table.add_row("[dim]Skipped[/dim]", str(stats.get("skipped", 0)))
    table.add_row("[red]Failed[/red]", str(stats.get("failed", 0)))
    tokens = session_token_counts()
    table.add_row("[dim]API cost (session)[/dim]", f"${tokens['cost_usd']:.4f}")
    console.print(Panel(table, title="Session Stats", border_style="dim"))


def review_jobs(
    jobs: list[Job],
    apply_fn,   # callable(job, auto_mode=False) -> ApplicationResult
    store: JobStore,
    start_auto: bool = False,
) -> None:
    """
    Interactive review loop. apply_fn is called for each job the user approves.

    Keys:
      a — apply to this job
      s — skip this job
      A — auto-apply to remaining jobs
      v — view full description
      q — quit
    """
    if not jobs:
        console.print("[yellow]No pending jobs to review.[/yellow]")
        return

    auto_mode = start_auto
    total = len(jobs)

    for i, job in enumerate(jobs, start=1):
        if auto_mode:
            console.print(f"[auto] Applying to {job.title} @ {job.company}...")
            result = apply_fn(job, auto_mode=True)
            status = "[green]Applied[/green]" if result.success else f"[red]Failed: {result.error}[/red]"
            console.print(f"  → {status}")
            continue

        # Prepare materials ahead of time (so user can preview cover letter)
        resume_path = None
        cover_letter = None
        try:
            from job_agent.application.applicator import Applicator
            # We expect apply_fn to have a .prepare() method accessible via closure or class
            if hasattr(apply_fn, '__self__') and hasattr(apply_fn.__self__, 'prepare'):
                resume_path, cover_letter = apply_fn.__self__.prepare(job)
        except Exception:
            pass

        console.clear()
        panel = render_job_panel(job, i, total, resume_path, cover_letter)
        console.print(panel)

        while True:
            try:
                key = Prompt.ask("", choices=["a", "s", "A", "v", "q"], default="s")
            except (KeyboardInterrupt, EOFError):
                key = "q"

            if key == "q":
                console.print("\n[dim]Quitting review.[/dim]")
                print_stats(store)
                return

            elif key == "s":
                store.update_job_status(job.id, "skipped")
                console.print("[dim]Skipped.[/dim]")
                break

            elif key == "a":
                console.print("[cyan]Applying...[/cyan]")
                pre = (resume_path, cover_letter) if resume_path and cover_letter else None
                result = apply_fn(job, auto_mode=False, pre_generated=pre)
                if result.success:
                    console.print("[green]Applied successfully![/green]")
                else:
                    console.print(f"[red]Application failed: {result.error}[/red]")
                break

            elif key == "A":
                console.print("[magenta]Auto-applying to remaining jobs...[/magenta]")
                auto_mode = True
                # Apply current job first
                pre = (resume_path, cover_letter) if resume_path and cover_letter else None
                result = apply_fn(job, auto_mode=True, pre_generated=pre)
                if result.success:
                    console.print(f"[green]Applied to {job.title} @ {job.company}[/green]")
                else:
                    console.print(f"[red]Failed: {result.error}[/red]")
                break

            elif key == "v":
                desc = job.description or "(no description)"
                console.print(Panel(
                    desc[:3000] + ("…" if len(desc) > 3000 else ""),
                    title="Job Description",
                    border_style="dim",
                ))
                # Don't break — let user choose action after viewing

    console.print("\n[bold]Review complete.[/bold]")
    print_stats(store)
