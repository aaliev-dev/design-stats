#!/usr/bin/env python3
"""
Fetch all Design issues from Jira with changelog + worklogs.
Stores raw JSON pages in data/ for caching, then builds SQLite database.
"""
import requests
import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "design_insights.db"

JIRA_BASE = "https://jira.int.agrd.dev"
JIRA_TOKEN = os.environ.get("AIGUARD_JIRA_TOKEN")
if not JIRA_TOKEN:
    print("ERROR: AIGUARD_JIRA_TOKEN env var not set")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {JIRA_TOKEN}",
    "Accept": "application/json",
}

JQL = (
    '(issuetype = Design OR assignee in ('
    '"a.aliev", '        # Alikhan Aliev
    '"JIRAUSER12200", '  # George Vorobyov
    '"JIRAUSER13105", '  # Stanislav Tartygin
    '"y.chernikova", '   # Yana Chernikova
    '"JIRAUSER12103", '  # Denis Spassky
    '"JIRAUSER12810", '  # Viktor Konovalov
    '"JIRAUSER12809"'    # Gulshat Sharipova
    ')) AND created >= "2018-01-01" ORDER BY created ASC'
)
PAGE_SIZE = 100  # Jira max for search


def fetch_page(start_at: int, page_size: int = PAGE_SIZE) -> dict:
    """Fetch one page of search results with expanded changelog."""
    params = {
        "jql": JQL,
        "startAt": start_at,
        "maxResults": page_size,
        "expand": "changelog",
        "fields": "*all",
    }
    for attempt in range(8):
        try:
            r = requests.get(
                f"{JIRA_BASE}/rest/api/2/search",
                headers=HEADERS,
                params=params,
                timeout=90,
            )
            if r.status_code == 200:
                return r.json()
            print(f"  WARN: status {r.status_code} (attempt {attempt+1}), resp: {r.text[:200]}")
            time.sleep(5 * (attempt + 1))
        except requests.exceptions.RequestException as e:
            print(f"  WARN: {e} (attempt {attempt+1})")
            time.sleep(10 * (attempt + 1))
    print(f"  FATAL: failed after 8 retries at startAt={start_at}")
    sys.exit(1)


def fetch_worklogs(issue_key: str) -> list:
    """Fetch full worklog list for an issue (when inline worklog has >20 entries)."""
    try:
        r = requests.get(
            f"{JIRA_BASE}/rest/api/2/issue/{issue_key}/worklog",
            headers=HEADERS,
            timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("worklogs", [])
    except:
        pass
    return []


def parse_ts(ts: str | None) -> str | None:
    """Parse Jira ISO timestamp to 'YYYY-MM-DD HH:MM:SS'."""
    if not ts:
        return None
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return None


def parse_ts_seconds(ts: str | None) -> float | None:
    """Parse Jira ISO timestamp to epoch seconds (for SQLite storage)."""
    if not ts:
        return None
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.timestamp()
    except:
        return None


def create_schema(conn: sqlite3.Connection):
    """Create SQLite tables."""
    c = conn.cursor()

    # Main issues table
    c.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            key TEXT PRIMARY KEY,
            id TEXT,
            project_key TEXT,
            project_name TEXT,
            summary TEXT,
            issue_type TEXT,
            status TEXT,
            status_category TEXT,
            priority TEXT,
            resolution TEXT,
            assignee_name TEXT,
            assignee_key TEXT,
            reporter_name TEXT,
            reporter_key TEXT,
            creator_name TEXT,
            creator_key TEXT,
            created TEXT,
            updated TEXT,
            resolution_date TEXT,
            due_date TEXT,
            time_spent INTEGER,
            time_estimate INTEGER,
            original_estimate INTEGER,
            aggregate_spent INTEGER,
            aggregate_estimate INTEGER,
            work_ratio REAL,
            labels TEXT,
            components TEXT,
            fix_versions TEXT,
            issue_links_count INTEGER,
            subtasks_count INTEGER,
            watch_count INTEGER,
            vote_count INTEGER
        )
    """)

    # Changelog table (all field changes)
    c.execute("""
        CREATE TABLE IF NOT EXISTS changelog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_key TEXT,
            created TEXT,
            created_epoch REAL,
            author_name TEXT,
            author_key TEXT,
            field TEXT,
            from_value TEXT,
            to_value TEXT,
            from_string TEXT,
            to_string TEXT,
            FOREIGN KEY (issue_key) REFERENCES issues(key)
        )
    """)

    # Status transitions (derived from changelog, only status field)
    c.execute("""
        CREATE TABLE IF NOT EXISTS status_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_key TEXT,
            transition_time TEXT,
            transition_epoch REAL,
            author_name TEXT,
            from_status TEXT,
            to_status TEXT,
            FOREIGN KEY (issue_key) REFERENCES issues(key)
        )
    """)

    # Worklogs
    c.execute("""
        CREATE TABLE IF NOT EXISTS worklogs (
            id TEXT PRIMARY KEY,
            issue_key TEXT,
            author_name TEXT,
            author_key TEXT,
            started TEXT,
            started_epoch REAL,
            created TEXT,
            time_spent_seconds INTEGER,
            time_spent_display TEXT,
            comment TEXT,
            FOREIGN KEY (issue_key) REFERENCES issues(key)
        )
    """)

    conn.commit()


def list_to_csv(items) -> str:
    """Join list of strings into comma-separated value."""
    if not items:
        return ""
    return ", ".join(str(i.get("name", i.get("key", ""))) for i in items) if isinstance(items[0], dict) else ", ".join(str(i) for i in items)


def store_issue(conn: sqlite3.Connection, issue: dict):
    """Store one issue and its changelog + worklogs."""
    c = conn.cursor()
    key = issue["key"]
    f = issue.get("fields", {})

    # Insert issue
    c.execute("""
        INSERT OR REPLACE INTO issues VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        key,
        issue.get("id"),
        f.get("project", {}).get("key"),
        f.get("project", {}).get("name"),
        f.get("summary"),
        f.get("issuetype", {}).get("name"),
        f.get("status", {}).get("name"),
        f.get("status", {}).get("statusCategory", {}).get("name"),
        f.get("priority", {}).get("name"),
        f.get("resolution", {}).get("name") if f.get("resolution") else None,
        f.get("assignee", {}).get("displayName") if f.get("assignee") else None,
        f.get("assignee", {}).get("key") if f.get("assignee") else None,
        f.get("reporter", {}).get("displayName") if f.get("reporter") else None,
        f.get("reporter", {}).get("key") if f.get("reporter") else None,
        f.get("creator", {}).get("displayName") if f.get("creator") else None,
        f.get("creator", {}).get("key") if f.get("creator") else None,
        parse_ts(f.get("created")),
        parse_ts(f.get("updated")),
        parse_ts(f.get("resolutiondate")),
        f.get("duedate"),
        f.get("timespent"),
        f.get("timeestimate"),
        f.get("timeoriginalestimate"),
        f.get("aggregatetimespent"),
        f.get("aggregatetimeestimate"),
        f.get("workratio"),
        ", ".join(f.get("labels", [])),
        ", ".join(comp.get("name", "") for comp in f.get("components", [])),
        ", ".join(v.get("name", "") for v in f.get("fixVersions", [])),
        len(f.get("issuelinks", [])),
        len(f.get("subtasks", [])),
        f.get("watches", {}).get("watchCount", 0) if f.get("watches") else 0,
        f.get("votes", {}).get("votes", 0) if f.get("votes") else 0,
    ))

    # Insert changelog entries
    cl = issue.get("changelog", {})
    for hist in cl.get("histories", []):
        created = parse_ts(hist.get("created"))
        created_epoch = parse_ts_seconds(hist.get("created"))
        author = hist.get("author", {})
        for item in hist.get("items", []):
            c.execute("""
                INSERT INTO changelog (issue_key, created, created_epoch, author_name, author_key,
                    field, from_value, to_value, from_string, to_string)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                key, created, created_epoch,
                author.get("displayName"), author.get("key"),
                item.get("field"),
                item.get("from"), item.get("to"),
                item.get("fromString"), item.get("toString"),
            ))

            # If this is a status change, record in status_transitions
            if item.get("field") in ("status", "Status"):
                c.execute("""
                    INSERT INTO status_transitions (issue_key, transition_time, transition_epoch, author_name, from_status, to_status)
                    VALUES (?,?,?,?,?,?)
                """, (
                    key, created, created_epoch,
                    author.get("displayName"),
                    item.get("fromString"), item.get("toString"),
                ))

    # Insert worklogs
    wl_field = f.get("worklog", {})
    wl_total = wl_field.get("total", 0) if wl_field else 0
    worklogs = wl_field.get("worklogs", []) if wl_field else []

    # If there are more than 20 worklogs, fetch full list
    if wl_total > 20:
        worklogs = fetch_worklogs(key)
        print(f"    Fetched {len(worklogs)} worklogs for {key} (was paginated)")

    for w in worklogs:
        wid = w.get("id", f"{key}-{w.get('started','?')}")
        c.execute("""
            INSERT OR REPLACE INTO worklogs VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            wid, key,
            w.get("author", {}).get("displayName"),
            w.get("author", {}).get("key"),
            parse_ts(w.get("started")),
            parse_ts_seconds(w.get("started")),
            parse_ts(w.get("created")),
            w.get("timeSpentSeconds"),
            w.get("timeSpent"),
            w.get("comment", "")[:500] if w.get("comment") else "",
        ))

    conn.commit()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old DB
    if DB_PATH.exists():
        DB_PATH.unlink()
        print("Removed old database.")

    conn = sqlite3.connect(str(DB_PATH))
    create_schema(conn)

    # Phase 1: Fetch all issues
    print("=" * 60)
    print("Phase 1: Fetching Design issues from Jira")
    print("=" * 60)

    # Fetch first page to get total
    first = fetch_page(0, 1)
    total = first["total"]
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"Total design issues: {total}")
    print(f"Pages to fetch: {pages} (page size: {PAGE_SIZE})")

    stored = 0
    for page_num in range(pages):
        start_at = page_num * PAGE_SIZE
        page_file = DATA_DIR / f"page_{page_num:04d}.json"

        # Use cached page if exists
        if page_file.exists() and page_file.stat().st_size > 100:
            with open(page_file) as f:
                data = json.load(f)
            print(f"  [{page_num+1}/{pages}] cached ({len(data.get('issues',[]))} issues)")
        else:
            print(f"  [{page_num+1}/{pages}] fetching startAt={start_at}...", end=" ", flush=True)
            data = fetch_page(start_at, PAGE_SIZE)
            with open(page_file, "w") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"got {len(data.get('issues', []))} issues")

        issues = data.get("issues", [])
        for issue in issues:
            store_issue(conn, issue)
        stored += len(issues)

        # Small delay to be nice to Jira
        if page_num < pages - 1 and not page_file.exists():
            time.sleep(0.3)

    print(f"\nTotal stored: {stored} issues")

    # Phase 2: Build indexes
    print("\n" + "=" * 60)
    print("Phase 2: Building indexes")
    print("=" * 60)

    c = conn.cursor()
    c.execute("CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_issues_project ON issues(project_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_issues_assignee ON issues(assignee_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_issues_created ON issues(created)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_issues_resolution ON issues(resolution_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_changelog_key ON changelog(issue_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_transitions_key ON status_transitions(issue_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_worklogs_key ON worklogs(issue_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_worklogs_author ON worklogs(author_name)")
    conn.commit()

    # Phase 3: Print summary stats
    print("\n" + "=" * 60)
    print("Phase 3: Summary")
    print("=" * 60)

    c.execute("SELECT COUNT(*) FROM issues")
    print(f"Total issues: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM changelog")
    print(f"Total changelog entries: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM status_transitions")
    print(f"Total status transitions: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM worklogs")
    print(f"Total worklog entries: {c.fetchone()[0]}")

    c.execute("""
        SELECT status, COUNT(*) as cnt FROM issues
        GROUP BY status ORDER BY cnt DESC LIMIT 15
    """)
    print("\nTop statuses:")
    for row in c.fetchall():
        print(f"  {row[0]:30s} {row[1]}")

    c.execute("""
        SELECT project_key, COUNT(*) as cnt FROM issues
        GROUP BY project_key ORDER BY cnt DESC
    """)
    print("\nBy project:")
    for row in c.fetchall():
        print(f"  {row[0]:10s} {row[1]}")

    c.execute("""
        SELECT assignee_name, COUNT(*) as cnt FROM issues
        WHERE assignee_name IS NOT NULL
        GROUP BY assignee_name ORDER BY cnt DESC LIMIT 10
    """)
    print("\nTop assignees:")
    for row in c.fetchall():
        print(f"  {row[0]:30s} {row[1]}")

    c.execute("""
        SELECT author_name, COUNT(*) as cnt, SUM(time_spent_seconds) as total_sec
        FROM worklogs WHERE author_name IS NOT NULL
        GROUP BY author_name ORDER BY total_sec DESC LIMIT 10
    """)
    print("\nTop time loggers:")
    for row in c.fetchall():
        hours = (row[2] or 0) / 3600
        print(f"  {row[0]:30s} {row[1]:4d} entries, {hours:8.1f}h")

    conn.close()
    print(f"\nDatabase: {DB_PATH}")
    print(f"Cache JSON: {DATA_DIR}/")
    print("\nDone!")


if __name__ == "__main__":
    main()
