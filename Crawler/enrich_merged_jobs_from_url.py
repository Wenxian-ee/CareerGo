#!/usr/bin/env python3
"""
For merged_jobs with no skills backfilled, re-fetch the detail URL and concatenate the Requirements / Responsibilities / Skills sections into full_description for subsequent SkillExtraction pipeline.
"""
from __future__ import annotations
import argparse
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Allow: python /path/to/Crawler/enrich_merged_jobs_from_url.py
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import psycopg2
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from config import DATABASE_CONFIG, MERGED_JOBS_TABLE
from html_parser_utils import parse_jobs_ac_uk_page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Must match the marker appended in enrich_job_row(); used to skip re-processing
_ENRICH_MARKER = "--- [enriched from job URL] ---"

_thread_local = threading.local()

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CareerGoEnricher/1.0; +https://example.invalid)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _thread_session() -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update(DEFAULT_HEADERS)
        _thread_local.session = s
    return s

# Section titles related to skill extraction (structured_sections in uppercase)
_SECTION_KEY_RE = re.compile(
    r"(RESPONSIBILIT|REQUIREMENT|SKILL|QUALIFICATION|EXPERIENCE|"
    r"ABOUT\s+THE\s+ROLE|PERSON\s+SPECIFICATION|ESSENTIAL|DESIRABLE|"
    r"EDUCATION|COMPETENC)",
    re.IGNORECASE,
)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _is_jobs_ac_uk(url: str) -> bool:
    return _host(url).endswith("jobs.ac.uk")


def _is_adzuna_portal(url: str) -> bool:
    h = _host(url)
    return h.endswith("adzuna.co.uk") or h.endswith("adzuna.com") or h == "www.adzuna.co.uk"


def _strip_boilerplate_soup(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for sel in ("nav", "footer", "header", "[role='navigation']"):
        for t in soup.select(sel):
            t.decompose()


def _generic_main_text(html: str, max_chars: int = 120_000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    _strip_boilerplate_soup(soup)
    main = (
        soup.select_one("main")
        or soup.select_one("article")
        or soup.select_one("#content")
        or soup.select_one(".content")
        or soup.body
    )
    if not main:
        return ""
    text = main.get_text("\n", strip=True)
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _parse_adzuna_dom(soup: BeautifulSoup) -> Dict[str, Any]:
    """Common container for Adzuna job pages (no official documentation, heuristic selectors)"""
    out: Dict[str, Any] = {"sections": {}}
    node = (
        soup.select_one("[data-testid='job-description']")
        or soup.select_one("[data-testid='description']")
        or soup.find("div", class_=re.compile(r"job-description|JobDescription", re.I))
        or soup.select_one("#job-description")
        or soup.select_one(".job-description")
    )
    if node:
        txt = node.get_text("\n", strip=True)
        if txt and len(txt) > 80:
            out["full_description"] = txt
    return out


def _parse_heading_sections(soup: BeautifulSoup) -> Dict[str, str]:
    """Split paragraphs by h2/h3 titles, making it easier to pick Responsibilities / Skills blocks by keywords"""
    sections: Dict[str, str] = {}
    for h in soup.find_all(["h2", "h3"]):
        title = h.get_text(" ", strip=True)
        if not title or len(title) > 220:
            continue
        parts: List[str] = []
        for sib in h.find_next_siblings():
            if sib.name in ("h1", "h2", "h3"):
                break
            if not hasattr(sib, "get_text"):
                continue
            txt = sib.get_text("\n", strip=True)
            if txt and len(txt) > 15:
                parts.append(txt)
        if parts:
            sections[title] = "\n".join(parts)
    return sections


def parse_generic_job_page(html: str) -> Dict[str, Any]:
    """
    Employer site / Adzuna fallback: main text + title-based blocks
    """
    soup = BeautifulSoup(html, "html.parser")
    _strip_boilerplate_soup(soup)

    parsed: Dict[str, Any] = {"sections": {}}

    adz = _parse_adzuna_dom(soup)
    if adz.get("full_description"):
        parsed["full_description"] = adz["full_description"]

    heading_secs = _parse_heading_sections(soup)
    for k, v in heading_secs.items():
        parsed["sections"][k] = v

    if not parsed.get("full_description"):
        parsed["full_description"] = _generic_main_text(html)

    return parsed


def _parse_page_for_url(fetch_url: str, html: str) -> Dict[str, Any]:
    """Select parser based on final URL hostname"""
    if _is_jobs_ac_uk(fetch_url):
        return parse_jobs_ac_uk_page(html)
    if _is_adzuna_portal(fetch_url):
        soup = BeautifulSoup(html, "html.parser")
        _strip_boilerplate_soup(soup)
        adz = _parse_adzuna_dom(soup)
        adz.setdefault("sections", {})
        hs = _parse_heading_sections(soup)
        for k, v in hs.items():
            adz["sections"][k] = v
        if not adz.get("full_description"):
            adz["full_description"] = _generic_main_text(html)
        return adz
    return parse_generic_job_page(html)


def candidate_fetch_urls(
    source: str,
    url: Optional[str],
    redirect_url: Optional[str],
    apply_url: Optional[str],
) -> List[str]:
    """
    Return a list of HTTP URLs to try (deduplicated).

    For Adzuna rows the ``redirect_url`` typically points at the employer
    site and is preferred over the internal ``url`` column.
    """
    raw: List[Optional[str]] = []
    s = (source or "").strip().lower()
    if s == "adzuna":
        raw = [redirect_url, apply_url, url]
    else:
        raw = [url]

    seen = set()
    out: List[str] = []
    for u in raw:
        if not u:
            continue
        u = str(u).strip()
        if not u.startswith("http"):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _collect_supplement(parsed: Dict[str, Any]) -> str:
    """Extract text blocks related to responsibilities/requirements/skills from the parsing results"""
    chunks: List[str] = []

    for key in ("requirements", "responsibilities", "full_description"):
        val = parsed.get(key)
        if isinstance(val, str) and val.strip():
            chunks.append(val.strip())

    sections = parsed.get("sections") or {}
    if isinstance(sections, dict):
        for title, body in sections.items():
            if not isinstance(body, str) or not body.strip():
                continue
            t = title or ""
            if _SECTION_KEY_RE.search(t):
                chunks.append(f"[{t.strip()}]\n{body.strip()}")

    # Deduplicate (maintain order)
    seen = set()
    out: List[str] = []
    for c in chunks:
        h = hash(c[:2000])
        if h in seen:
            continue
        seen.add(h)
        out.append(c)

    return "\n\n".join(out)


def fetch_html(url: str, timeout: float) -> Tuple[Optional[str], Optional[str]]:
    try:
        r = _thread_session().get(url, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            return None, f"skip content-type {ctype!r}"
        return r.text, None
    except requests.RequestException as e:
        return None, str(e)


def enrich_job_row(
    source: str,
    url: Optional[str],
    redirect_url: Optional[str],
    apply_url: Optional[str],
    existing_full: Optional[str],
    timeout: float,
    min_supplement_chars: int,
) -> Tuple[Optional[str], str]:
    """
    Returns (new_full_description_or_none, status_message).
    Try multiple URLs in order of source (Adzuna prioritizes employer redirect), until the supplement text is long enough.
    """
    candidates = candidate_fetch_urls(source, url, redirect_url, apply_url)
    if not candidates:
        return None, "no_http_url"

    errors: List[str] = []
    for fetch_url in candidates:
        html, err = fetch_html(fetch_url, timeout=timeout)
        if not html:
            errors.append(f"{fetch_url[:48]}… -> {err}")
            continue

        parsed = _parse_page_for_url(fetch_url, html)
        supplement = _collect_supplement(parsed)
        if len(supplement) < min_supplement_chars:
            errors.append(f"{fetch_url[:48]}… -> supplement_too_short:{len(supplement)}")
            continue

        base = (existing_full or "").strip()
        marker = f"\n\n{_ENRICH_MARKER}\n\n"
        if base:
            merged = base + marker + supplement
        else:
            merged = supplement

        return merged, f"ok ({(source or '?')[:12]} via {fetch_url[:70]})"

    return None, " | ".join(errors[:3]) if errors else "no_content"


def _enrich_one_row(
    row: Tuple[Any, ...],
    timeout: float,
    min_supplement_chars: int,
) -> Tuple[Any, Optional[str], str]:
    job_id, source, url, redirect_url, apply_url, full_description = row
    if not candidate_fetch_urls(source or "", url, redirect_url, apply_url):
        return job_id, None, "no_http_url"
    new_full, status = enrich_job_row(
        source or "",
        url,
        redirect_url,
        apply_url,
        full_description,
        timeout=timeout,
        min_supplement_chars=min_supplement_chars,
    )
    return job_id, new_full, status


def main() -> int:
    ap = argparse.ArgumentParser(description="Enrich merged_jobs.full_description from detail URL")
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N rows after ORDER BY merged_at DESC (newest first); use for incremental runs, e.g. --limit 200 for ~200 new rows",
    )
    ap.add_argument(
        "--include-already-enriched",
        action="store_true",
        help="Also select rows whose full_description already contains the URL-enrich marker (default: skip them to avoid duplicate appends)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Do not UPDATE database")
    ap.add_argument("--timeout", type=float, default=25.0)
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.8,
        help="Delay after each row when --workers 1 (politeness); ignored when workers>1",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=8,
        metavar="N",
        help="Concurrent HTTP threads (I/O bound); use 1 for sequential + --sleep throttling",
    )
    ap.add_argument(
        "--batch-commit",
        type=int,
        default=50,
        metavar="N",
        help="Commit every N successful UPDATEs (ignored with --dry-run)",
    )
    ap.add_argument(
        "--min-supplement-chars",
        type=int,
        default=80,
        help="Minimum chars of extracted supplement to accept",
    )
    ap.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable tqdm progress bar (e.g. for cleaner log-only output)",
    )
    ap.add_argument(
        "--log-every",
        type=int,
        default=100,
        metavar="N",
        help="Print a summary line every N rows (ok/fail/nourl/success rate); 0 means only use progress bar postfix. Default 100",
    )
    args = ap.parse_args()

    if args.limit is not None and args.limit <= 0:
        logger.error("--limit must be a positive integer")
        return 2
    if args.workers < 1:
        logger.error("--workers must be >= 1")
        return 2
    if args.batch_commit < 1:
        logger.error("--batch-commit must be >= 1")
        return 2
    if args.log_every < 0:
        logger.error("--log-every must be >= 0")
        return 2

    if args.limit:
        logger.info("Row cap: first %s candidates (SQL LIMIT)", args.limit)
    else:
        logger.info(
            "No --limit: processing all rows matching empty requirements + URL"
            + ("" if args.include_already_enriched else " (excluding already URL-enriched rows)")
        )

    if args.workers > 1:
        logger.info("Concurrency: %s workers, batch commit every %s rows", args.workers, args.batch_commit)
    else:
        logger.info("Sequential mode: --sleep %.3fs between processed rows", args.sleep)

    conn = psycopg2.connect(**DATABASE_CONFIG)
    cur = conn.cursor()

    # Same as integrated_pipeline._requirements_empty_sql: skills column is unfilled
    # Adzuna rows may only need redirect_url to be re-fetched, so (url OR redirect_url OR apply_url) is not empty
    skip_enriched_clause = ""
    if not args.include_already_enriched:
        # Avoid re-appending supplement when requirements are still empty after a prior enrich run
        skip_enriched_clause = (
            f"  AND (full_description IS NULL OR position('{_ENRICH_MARKER}' in full_description) = 0)\n"
        )

    sql = f"""
        SELECT job_id, source, url, redirect_url, apply_url, full_description
        FROM {MERGED_JOBS_TABLE}
        WHERE (
            url IS NOT NULL AND BTRIM(url) <> ''
            OR redirect_url IS NOT NULL AND BTRIM(redirect_url) <> ''
            OR apply_url IS NOT NULL AND BTRIM(apply_url) <> ''
          )
          AND (
            requirements IS NULL
            OR TRIM(requirements::text) = ''
            OR TRIM(requirements::text) = '[]'
          )
{skip_enriched_clause}        ORDER BY merged_at DESC NULLS LAST
    """
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    cur.execute(sql)
    rows = cur.fetchall()
    logger.info("Candidates: %s rows", len(rows))
    if args.log_every:
        logger.info(
            "Visibility: progress bar right ok=successfully enriched fail=fetch/parse failure nourl=no available URL;"
            "Also print a summary line every %s rows (can be disabled with --log-every 0).",
            args.log_every,
        )

    ok = 0
    skipped = 0
    enrich_failures = 0
    n_no_url = 0
    failure_samples: List[str] = []
    _MAX_FAILURE_SAMPLES = 25

    dbg_url: Dict[Any, str] = {}
    for job_id, _src, url, redirect_url, apply_url, _fd in rows:
        dbg_url[job_id] = (url or redirect_url or apply_url or "")[:80]

    pending_commit: List[Tuple[str, Any]] = []

    def _flush_pending() -> None:
        if args.dry_run or not pending_commit:
            pending_commit.clear()
            return
        cur.executemany(
            f"""
            UPDATE {MERGED_JOBS_TABLE}
            SET full_description = %s
            WHERE job_id = %s
            """,
            pending_commit,
        )
        conn.commit()
        pending_commit.clear()

    def _handle_result(job_id: Any, new_full: Optional[str], status: str) -> None:
        nonlocal ok, skipped, enrich_failures, n_no_url

        if not new_full:
            if status == "no_http_url":
                n_no_url += 1
                skipped += 1
                return
            enrich_failures += 1
            if len(failure_samples) < _MAX_FAILURE_SAMPLES:
                udbg = dbg_url.get(job_id, "")
                failure_samples.append(f"{job_id} {udbg} — {status[:240]}")
            skipped += 1
            if args.workers == 1 and args.sleep > 0:
                time.sleep(args.sleep)
            return

        if args.dry_run:
            ok += 1
        else:
            pending_commit.append((new_full, job_id))
            if len(pending_commit) >= args.batch_commit:
                _flush_pending()
            ok += 1

        if args.workers == 1 and args.sleep > 0:
            time.sleep(args.sleep)

    futures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in rows:
            futures.append(
                pool.submit(
                    _enrich_one_row,
                    row,
                    args.timeout,
                    args.min_supplement_chars,
                )
            )

        done_iter: Any = as_completed(futures)
        pbar = None
        if not args.no_progress:
            pbar = tqdm(
                done_iter,
                total=len(futures),
                desc="Enrich full_description",
                unit="row",
                dynamic_ncols=True,
                mininterval=0.3,
                file=sys.stderr,
            )

        total_rows = len(futures)
        completed = 0
        for fut in pbar if pbar is not None else done_iter:
            job_id, new_full, status = fut.result()
            _handle_result(job_id, new_full, status)
            completed += 1

            if pbar is not None:
                rate_pct = 100.0 * ok / max(completed, 1)
                pbar.set_postfix(
                    ok=ok,
                    fail=enrich_failures,
                    nourl=n_no_url,
                    ok_pct=f"{rate_pct:.1f}%",
                    refresh=False,
                )

            if args.log_every and completed % args.log_every == 0:
                rate_pct = 100.0 * ok / max(completed, 1)
                line = (
                    f"[enrich] {completed}/{total_rows} "
                    f"ok={ok} fail={enrich_failures} nourl={n_no_url} "
                    f"success_rate={rate_pct:.1f}%"
                )
                if pbar is not None:
                    tqdm.write(line, file=sys.stderr)
                else:
                    logger.info(line)

    _flush_pending()

    cur.close()
    conn.close()
    logger.info(
        "Done: enriched=%s skipped=%s (enrich_failures=%s, no_http_url=%s)",
        ok,
        skipped,
        enrich_failures,
        n_no_url,
    )
    if failure_samples:
        logger.warning(
            "Enrich failure samples (showing up to %s of %s):\n%s",
            len(failure_samples),
            enrich_failures,
            "\n".join(failure_samples),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
