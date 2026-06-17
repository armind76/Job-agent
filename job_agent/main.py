"""CLI entry point: python -m job_agent [options]"""
import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console

console = Console()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="job-agent",
        description="Autonomous job application agent for C++/systems engineers in NYC",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Skip interactive review and apply to all priority-1/2 jobs automatically",
    )
    parser.add_argument(
        "--source",
        choices=["linkedin", "indeed", "glassdoor", "builtin", "all"],
        default="all",
        help="Which job board to scrape (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max jobs to scrape per source (default: 20)",
    )
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        help="Only review jobs of this tier (default: all tiers)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fill forms but do not submit. Logs form fields instead.",
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Override default search queries with a custom query",
    )
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="Skip scraping, go straight to reviewing pending jobs in DB",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print DB statistics and exit",
    )
    parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export all applied jobs to data/applications.csv and exit",
    )
    return parser.parse_args()


def _get_scrapers(source: str, store) -> list:
    from job_agent.scrapers.builtin_nyc import BuiltInNYCScraper
    from job_agent.scrapers.indeed import IndeedScraper
    from job_agent.scrapers.glassdoor import GlassdoorScraper
    from job_agent.scrapers.linkedin import LinkedInScraper

    all_scrapers = {
        "builtin": BuiltInNYCScraper,
        "indeed": IndeedScraper,
        "glassdoor": GlassdoorScraper,
        "linkedin": LinkedInScraper,
    }

    if source == "all":
        return [cls(store) for cls in all_scrapers.values()]
    elif source in all_scrapers:
        return [all_scrapers[source](store)]
    else:
        console.print(f"[red]Unknown source: {source}[/red]")
        return []


async def _scrape_and_classify(scrapers, args, store, client):
    """Run scrapers, store jobs, classify them with Claude."""
    from job_agent.ai.classifier import classify_job

    total_new = 0
    for scraper in scrapers:
        console.print(f"[cyan]Scraping {scraper.source_name}...[/cyan]")
        try:
            jobs = await scraper.scrape(query=args.query, limit=args.limit)
            new_count = 0
            for job in jobs:
                if store.upsert_job(job):
                    new_count += 1
                    total_new += 1

                # Classify if not already classified
                db_job = store.get_job(job.id)
                if db_job and db_job.priority_tier is None:
                    result = classify_job(db_job, client)
                    if result.skip:
                        store.update_job_status(job.id, "skipped")
                    else:
                        store.update_job_classification(
                            job.id,
                            tier=result.tier,
                            score=result.score,
                            reason=result.reason,
                        )
            console.print(f"  → {len(jobs)} found, {new_count} new")
        except Exception as e:
            console.print(f"  [red]Error scraping {scraper.source_name}: {e}[/red]")

    return total_new


def main() -> None:
    args = _parse_args()

    # Lazy imports to keep startup fast
    from config.settings import settings
    from job_agent.db.store import JobStore
    from job_agent.ai.client import AIClient

    # Validate API key
    if not settings.anthropic_api_key and not args.review_only:
        console.print("[red]ANTHROPIC_API_KEY not set. Add it to .env[/red]")
        sys.exit(1)

    # Initialise store
    store = JobStore(settings.db_path)
    client = AIClient() if settings.anthropic_api_key else None

    if args.stats:
        from job_agent.ui.cli import print_stats
        print_stats(store)
        store.close()
        return

    if args.export_csv:
        from job_agent.export import export_csv
        path = export_csv(store)
        console.print(f"[green]Exported to {path}[/green]")
        store.close()
        return

    # ── Phase 1: Scrape ───────────────────────────────────────────
    if not args.review_only:
        scrapers = _get_scrapers(args.source, store)
        if not scrapers:
            store.close()
            sys.exit(1)

        total_new = asyncio.run(
            _scrape_and_classify(scrapers, args, store, client)
        )
        console.print(f"\n[bold]Scraped {total_new} new jobs total.[/bold]")

    # ── Phase 2: Review / Apply ───────────────────────────────────
    from job_agent.application.quota import select_with_graphics_quota, quota_summary

    # Fetch a generous pool so the quota selector has enough candidates.
    raw_pending = store.get_pending_jobs(
        tier_filter=args.tier,
        limit=500,
    )

    # Apply 10% graphics quota only when not explicitly filtering to a single tier.
    if args.tier is None:
        pending = select_with_graphics_quota(raw_pending, limit=args.limit * 2)
        console.print(f"[dim]Graphics quota applied: {quota_summary(pending)}[/dim]")
    else:
        pending = raw_pending[: args.limit * 2]

    if not pending:
        console.print("[yellow]No pending jobs to review.[/yellow]")
        store.close()
        return

    console.print(f"[bold]{len(pending)} pending jobs to review.[/bold]")

    if client is None:
        console.print("[red]Cannot apply without ANTHROPIC_API_KEY[/red]")
        store.close()
        return

    from job_agent.application.applicator import Applicator
    from job_agent.ui.cli import review_jobs

    applicator = Applicator(store, client)

    def apply_fn(job, auto_mode=False, pre_generated=None):
        return applicator.apply_sync(
            job,
            auto_mode=auto_mode,
            dry_run=args.dry_run,
            pre_generated=pre_generated,
        )

    # Bind prepare so cli.py can call it for preview
    apply_fn.__self__ = applicator

    if args.auto:
        # Auto mode: apply to all without review
        console.print("[magenta]Auto mode: applying to all pending jobs...[/magenta]")
        for job in pending:
            console.print(f"  Applying to [cyan]{job.title}[/cyan] @ {job.company}...")
            result = applicator.apply_sync(job, auto_mode=True, dry_run=args.dry_run)
            status = "[green]OK[/green]" if result.success else f"[red]FAIL: {result.error}[/red]"
            console.print(f"    → {status}")
    else:
        review_jobs(pending, apply_fn, store)

    store.close()


if __name__ == "__main__":
    main()
