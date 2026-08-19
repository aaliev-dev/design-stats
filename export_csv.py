#!/usr/bin/env python3
"""
Export key metrics from SQLite to CSV files for easy viewing in Excel/Numbers.
"""
import sqlite3
import csv
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "design_insights.db"
EXPORT_DIR = BASE_DIR / "csv_exports"

QUERIES = {
    "issues_all.csv": """
        SELECT key, project_key, project_name, summary, issue_type, status, status_category,
               priority, resolution, assignee_name, reporter_name, creator_name,
               created, updated, resolution_date, due_date,
               time_spent, time_estimate, original_estimate, work_ratio,
               labels, components, fix_versions
        FROM issues ORDER BY created
    """,
    "status_summary.csv": """
        SELECT status, COUNT(*) as count
        FROM issues GROUP BY status ORDER BY count DESC
    """,
    "by_project.csv": """
        SELECT project_key, project_name,
               COUNT(*) as total,
               SUM(CASE WHEN resolution IS NOT NULL THEN 1 ELSE 0 END) as resolved,
               SUM(CASE WHEN resolution IS NULL THEN 1 ELSE 0 END) as unresolved
        FROM issues GROUP BY project_key, project_name ORDER BY total DESC
    """,
    "by_assignee.csv": """
        SELECT assignee_name, status, COUNT(*) as count
        FROM issues WHERE assignee_name IS NOT NULL
        GROUP BY assignee_name, status ORDER BY assignee_name, count DESC
    """,
    "throughput_year_month.csv": """
        SELECT
            strftime('%Y', created) as year,
            strftime('%m', created) as month,
            COUNT(*) as created_count,
            SUM(CASE WHEN resolution_date IS NOT NULL THEN 1 ELSE 0 END) as resolved_count
        FROM issues
        GROUP BY year, month ORDER BY year, month
    """,
    "worklogs_all.csv": """
        SELECT issue_key, author_name, started, time_spent_seconds, time_spent_display, comment
        FROM worklogs ORDER BY started
    """,
    "time_by_person.csv": """
        SELECT author_name,
               COUNT(*) as entries,
               SUM(time_spent_seconds) as total_seconds,
               ROUND(SUM(time_spent_seconds) / 3600.0, 2) as total_hours,
               COUNT(DISTINCT issue_key) as issues_worked
        FROM worklogs WHERE author_name IS NOT NULL
        GROUP BY author_name ORDER BY total_hours DESC
    """,
    "status_transitions.csv": """
        SELECT issue_key, transition_time, author_name, from_status, to_status
        FROM status_transitions ORDER BY issue_key, transition_time
    """,
    "cycle_time_per_status.csv": """
        WITH transitions AS (
            SELECT
                issue_key,
                to_status,
                transition_epoch,
                LEAD(transition_epoch) OVER (PARTITION BY issue_key ORDER BY transition_epoch) as next_epoch,
                LEAD(to_status) OVER (PARTITION BY issue_key ORDER BY transition_epoch) as next_status
            FROM status_transitions
        ),
        durations AS (
            SELECT
                to_status as status,
                (next_epoch - transition_epoch) / 3600.0 as hours_in_status
            FROM transitions
            WHERE next_epoch IS NOT NULL AND transition_epoch IS NOT NULL
        )
        SELECT
            status,
            COUNT(*) as transition_count,
            ROUND(AVG(hours_in_status), 1) as avg_hours,
            ROUND(MIN(hours_in_status), 1) as min_hours,
            ROUND(MAX(hours_in_status), 1) as max_hours
        FROM durations
        WHERE hours_in_status > 0
        GROUP BY status ORDER BY avg_hours DESC
    """,
    "issue_lifecycle.csv": """
        SELECT
            i.key,
            i.project_key,
            i.status as current_status,
            i.created,
            i.resolution_date,
            ROUND((CAST(strftime('%s', COALESCE(i.resolution_date, datetime('now'))) AS REAL)
                  - CAST(strftime('%s', i.created) AS REAL)) / 86400.0, 1) as total_lifetime_days,
            COUNT(st.id) as status_changes
        FROM issues i
        LEFT JOIN status_transitions st ON st.issue_key = i.key
        GROUP BY i.key
        ORDER BY total_lifetime_days DESC
    """,
    "priority_breakdown.csv": """
        SELECT priority, status, COUNT(*) as count
        FROM issues
        WHERE priority IS NOT NULL
        GROUP BY priority, status ORDER BY priority, count DESC
    """,
    "worklog_coverage_by_project.csv": """
        SELECT i.project_key,
               COUNT(*) as total_issues,
               COUNT(DISTINCT w.issue_key) as issues_with_worklogs,
               ROUND(COUNT(DISTINCT w.issue_key) * 100.0 / COUNT(*), 1) as coverage_pct
        FROM issues i
        LEFT JOIN worklogs w ON w.issue_key = i.key
        GROUP BY i.project_key ORDER BY coverage_pct DESC
    """,
    "time_to_assignment.csv": """
        WITH first_assign AS (
            SELECT issue_key, MIN(created_epoch) as first_assign_epoch
            FROM changelog
            WHERE field = 'assignee'
            GROUP BY issue_key
        ),
        issue_created AS (
            SELECT key,
                   CAST(strftime('%s', created) AS REAL) as created_epoch,
                   assignee_name, project_key
            FROM issues WHERE created IS NOT NULL
        )
        SELECT ic.key, ic.project_key, ic.assignee_name,
               ROUND((fa.first_assign_epoch - ic.created_epoch) / 86400.0, 1) as days_to_assign
        FROM issue_created ic
        JOIN first_assign fa ON fa.issue_key = ic.key
        WHERE days_to_assign >= 0
        ORDER BY days_to_assign DESC
    """,
    "estimation_accuracy.csv": """
        SELECT key, project_key, assignee_name,
               original_estimate, time_spent,
               ROUND(CAST(time_spent AS REAL) / NULLIF(original_estimate, 0), 3) as ratio,
               ROUND(original_estimate / 3600.0, 1) as est_hours,
               ROUND(time_spent / 3600.0, 1) as actual_hours
        FROM issues
        WHERE original_estimate IS NOT NULL AND time_spent IS NOT NULL
          AND original_estimate > 0 AND time_spent > 0
        ORDER BY ratio DESC
    """,
    "stale_tasks.csv": """
        WITH last_trans AS (
            SELECT issue_key, MAX(transition_epoch) as last_epoch
            FROM status_transitions
            GROUP BY issue_key
        )
        SELECT i.key, i.project_key, i.summary, i.status, i.assignee_name,
               ROUND((strftime('%s','now') - lt.last_epoch) / 86400.0, 1) as days_since_last_transition
        FROM issues i
        LEFT JOIN last_trans lt ON lt.issue_key = i.key
        WHERE i.status_category != 'Done'
        ORDER BY days_since_last_transition DESC
    """,
    "most_churned.csv": """
        SELECT i.key, i.project_key, i.summary, i.status, i.assignee_name,
               COUNT(st.id) as transition_count
        FROM issues i
        JOIN status_transitions st ON st.issue_key = i.key
        GROUP BY i.key
        ORDER BY transition_count DESC
        LIMIT 50
    """,
}


def main():
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Run fetch_data.py first.")
        return

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    for filename, query in QUERIES.items():
        path = EXPORT_DIR / filename
        try:
            cursor = conn.execute(query)
            headers = [d[0] for d in cursor.description]
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(cursor)
            print(f"  ✓ {filename} ({cursor.rowcount} rows)")
        except Exception as e:
            print(f"  ✗ {filename}: {e}")

    conn.close()
    print(f"\nCSVs exported to: {EXPORT_DIR}")


if __name__ == "__main__":
    main()
