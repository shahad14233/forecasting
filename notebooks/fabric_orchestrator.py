"""Notebook-friendly orchestrator for scheduled execution in Fabric.

This module can be imported directly in a Fabric Notebook and executed without
shell subprocesses.
"""

import os
from typing import Optional

from src.tenders_pipeline import SiteConfig, TendersPipeline


def run_pipeline(output_dir: Optional[str] = None, max_competitions: Optional[int] = None) -> None:
    default_fabric_output = "/lakehouse/default/Files/tenders_pipeline"
    resolved_output = output_dir or os.environ.get("TENDERS_OUTPUT_DIR", default_fabric_output)

    site_config = SiteConfig(
        username_selector=os.environ.get("TENDERS_USERNAME_SELECTOR", 'input[name="username"]'),
        password_selector=os.environ.get("TENDERS_PASSWORD_SELECTOR", 'input[name="password"]'),
        submit_selector=os.environ.get("TENDERS_SUBMIT_SELECTOR", 'button[type="submit"]'),
        post_login_url_pattern=os.environ.get("TENDERS_POST_LOGIN_URL_PATTERN", "**/dashboard"),
        competition_link_selector=os.environ.get("TENDERS_COMPETITION_LINK_SELECTOR", "a.competition-link"),
    )

    pipeline = TendersPipeline(
        base_url=os.environ.get("TENDERS_BASE_URL", "https://example.com"),
        competitions_url=os.environ.get("TENDERS_COMPETITIONS_URL", "https://example.com/competitions"),
        username=os.environ.get("TENDERS_USERNAME", ""),
        password=os.environ.get("TENDERS_PASSWORD", ""),
        output_dir=resolved_output,
        headless=os.environ.get("HEADLESS", "1") == "1",
        max_competitions=max_competitions or int(os.environ.get("MAX_COMPETITIONS", "0") or 0) or None,
        site_config=site_config,
    )
    pipeline.run()


if __name__ == "__main__":
    run_pipeline()
