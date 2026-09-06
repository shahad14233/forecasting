from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
import argparse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


@dataclass
class TenderRecord:
    tender_id: str
    tender_name: str
    entity_name: str
    status: str
    documents_fee: str
    submission_deadline: str
    opening_date: str
    supplier_name: str
    award_announcement: str
    classification_scope: str
    execution_location: str
    local_content_mechanism: str
    source_url: str
    pulled_at_utc: str


@dataclass
class SiteConfig:
    username_selector: str = 'input[name="username"]'
    password_selector: str = 'input[name="password"]'
    submit_selector: str = 'button[type="submit"]'
    post_login_url_pattern: str = "**/dashboard"
    competition_link_selector: str = "a.competition-link"


class TendersPipeline:
    """Deterministic browser automation pipeline for tenders pages.

    Layers:
    - Bronze: raw html/json snapshots
    - Silver: structured csv table
    - Gold: reporting-ready csv table
    """

    def __init__(
        self,
        base_url: str,
        competitions_url: str,
        username: str,
        password: str,
        output_dir: str = "output",
        headless: bool = True,
        max_competitions: int | None = None,
        site_config: SiteConfig | None = None,
    ) -> None:
        self.base_url = base_url
        self.competitions_url = competitions_url
        self.username = username
        self.password = password
        self.output_root = Path(output_dir)
        self.bronze_dir = self.output_root / "bronze"
        self.silver_dir = self.output_root / "silver"
        self.gold_dir = self.output_root / "gold"
        self.headless = headless
        self.max_competitions = max_competitions
        self.site_config = site_config or SiteConfig()

        self.bronze_dir.mkdir(parents=True, exist_ok=True)
        self.silver_dir.mkdir(parents=True, exist_ok=True)
        self.gold_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        logging.info("Starting tenders pipeline")
        existing_ids = self._load_existing_tender_ids(self.silver_dir / "tenders_structured.csv")
        records: list[TenderRecord] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(locale="ar-SA")
            page = context.new_page()

            self._login(page)
            competition_links = list(self._extract_competition_links(page))
            if self.max_competitions:
                competition_links = competition_links[: self.max_competitions]

            for link in competition_links:
                try:
                    tender_id = self._extract_tender_id(link)
                    if tender_id and tender_id in existing_ids:
                        logging.info("Skipping existing tender %s", tender_id)
                        continue

                    record = self._extract_competition_record(page, link)
                    records.append(record)
                except Exception as exc:
                    logging.exception("Failed processing %s: %s", link, exc)
                    self._safe_screenshot(page, f"failed_{int(time.time())}.png")

            browser.close()

        self._write_structured(records)
        self._write_gold(records)
        logging.info("Pipeline completed. Processed %s records", len(records))

    def _login(self, page) -> None:
        logging.info("Logging in")
        page.goto(self.base_url, wait_until="domcontentloaded")
        page.fill(self.site_config.username_selector, self.username)
        page.fill(self.site_config.password_selector, self.password)
        page.click(self.site_config.submit_selector)
        page.wait_for_url(self.site_config.post_login_url_pattern, timeout=30000)

    def _extract_competition_links(self, page) -> Iterable[str]:
        logging.info("Opening competitions list")
        page.goto(self.competitions_url, wait_until="domcontentloaded")
        page.wait_for_selector(self.site_config.competition_link_selector, timeout=30000)

        anchors = page.locator(self.site_config.competition_link_selector)
        links = []
        for i in range(anchors.count()):
            href = anchors.nth(i).get_attribute("href")
            if href:
                full_url = href if href.startswith("http") else f"{self.base_url.rstrip('/')}/{href.lstrip('/')}"
                links.append(full_url)

        ts = int(time.time())
        (self.bronze_dir / f"competitions_list_{ts}.json").write_text(
            json.dumps({"links": links}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return links

    def _extract_competition_record(self, page, url: str) -> TenderRecord:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("body", timeout=15000)

        html = page.content()
        tender_id = self._extract_tender_id(url) or self._field_by_label(page, "رقم المنافسة")
        ts = int(time.time())
        raw_path = self.bronze_dir / f"{tender_id or 'unknown'}_{ts}.html"
        raw_path.write_text(html, encoding="utf-8")

        tabs = [
            "المعلومات الأساسية",
            "العناوين والمواعيد",
            "مجال التصنيف وموقع التنفيذ",
            "آليات المحتوى المحلي",
            "إعلان نتائج الترسية",
        ]
        for tab in tabs:
            self._click_tab_if_exists(page, tab)
            tab_html = page.locator("body").inner_html()
            safe_tab = re.sub(r"\s+", "_", tab)
            (self.bronze_dir / f"{tender_id}_{safe_tab}_{ts}.html").write_text(tab_html, encoding="utf-8")

        return TenderRecord(
            tender_id=tender_id or "",
            tender_name=self._field_by_label(page, "اسم المنافسة"),
            entity_name=self._field_by_label(page, "الجهة الحكومية"),
            status=self._field_by_label(page, "حالة المنافسة"),
            documents_fee=self._field_by_label(page, "قيمة الوثائق"),
            submission_deadline=self._field_by_label(page, "آخر موعد لتقديم العروض"),
            opening_date=self._field_by_label(page, "تاريخ فتح العروض"),
            supplier_name=self._field_by_label(page, "اسم المورد"),
            award_announcement=self._field_by_label(page, "إعلان نتائج الترسية"),
            classification_scope=self._field_by_label(page, "مجال التصنيف"),
            execution_location=self._field_by_label(page, "موقع التنفيذ"),
            local_content_mechanism=self._field_by_label(page, "آليات المحتوى المحلي"),
            source_url=url,
            pulled_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    def _click_tab_if_exists(self, page, tab_name: str) -> None:
        tab = page.get_by_role("tab", name=tab_name)
        if tab.count() == 0:
            return
        tab.first.click()
        page.wait_for_timeout(500)

    def _field_by_label(self, page, label: str) -> str:
        """Reads value by Arabic label for stability instead of visual order."""
        selector = f"xpath=//*[contains(normalize-space(), '{label}')]/following::*[1]"
        try:
            node = page.locator(selector).first
            if node.count() == 0:
                return ""
            return node.inner_text().strip()
        except PlaywrightTimeoutError:
            return ""

    def _extract_tender_id(self, url: str) -> str:
        match = re.search(r"(tender|competition)[=/](\d+)", url, re.IGNORECASE)
        return match.group(2) if match else ""

    def _write_structured(self, records: list[TenderRecord]) -> None:
        if not records:
            return

        path = self.silver_dir / "tenders_structured.csv"
        write_header = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(records[0]).keys()))
            if write_header:
                writer.writeheader()
            for r in records:
                writer.writerow(asdict(r))

    def _write_gold(self, records: list[TenderRecord]) -> None:
        if not records:
            return

        path = self.gold_dir / "tenders_reporting.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            fields = [
                "tender_id",
                "tender_name",
                "entity_name",
                "status",
                "opening_date",
                "submission_deadline",
                "supplier_name",
                "award_announcement",
                "pulled_at_utc",
            ]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in records:
                row = asdict(r)
                writer.writerow({k: row.get(k, "") for k in fields})

    def _load_existing_tender_ids(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        ids: set[str] = set()
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tender_id = (row.get("tender_id") or "").strip()
                if tender_id:
                    ids.add(tender_id)
        return ids

    def _safe_screenshot(self, page, name: str) -> None:
        target = self.bronze_dir / name
        try:
            page.screenshot(path=str(target), full_page=True)
        except Exception:
            logging.warning("Unable to capture screenshot: %s", target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic Playwright pipeline for tenders")
    parser.add_argument("--base-url", default=os.environ.get("TENDERS_BASE_URL", "https://example.com"))
    parser.add_argument(
        "--competitions-url",
        default=os.environ.get("TENDERS_COMPETITIONS_URL", "https://example.com/competitions"),
    )
    parser.add_argument("--username", default=os.environ.get("TENDERS_USERNAME", ""))
    parser.add_argument("--password", default=os.environ.get("TENDERS_PASSWORD", ""))
    parser.add_argument("--output-dir", default=os.environ.get("TENDERS_OUTPUT_DIR", "output"))
    parser.add_argument("--headless", action="store_true", default=os.environ.get("HEADLESS", "1") == "1")
    parser.add_argument("--max-competitions", type=int, default=int(os.environ.get("MAX_COMPETITIONS", "0") or 0))
    parser.add_argument(
        "--site-config-json",
        default=os.environ.get("TENDERS_SITE_CONFIG_JSON", ""),
        help="Optional JSON for selectors/url pattern overrides",
    )
    args = parser.parse_args()

    site_config = SiteConfig()
    if args.site_config_json:
        overrides = json.loads(args.site_config_json)
        site_config = SiteConfig(**{**asdict(site_config), **overrides})

    pipeline = TendersPipeline(
        base_url=args.base_url,
        competitions_url=args.competitions_url,
        username=args.username,
        password=args.password,
        output_dir=args.output_dir,
        headless=args.headless,
        max_competitions=args.max_competitions or None,
        site_config=site_config,
    )
    pipeline.run()


if __name__ == "__main__":
    main()
