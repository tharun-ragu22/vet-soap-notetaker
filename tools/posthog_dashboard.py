"""Create the PostHog dashboard that answers the demo questions.

    POSTHOG_PERSONAL_API_KEY=phx_... uv run python -m tools.posthog_dashboard --environment demo

Builds "Vet Soap Notetaker (<environment>)": one tile per question, every tile
filtered to that environment so test runs never mix in. Every query is run
against the project first, so a broken query fails here instead of becoming an
empty tile. Re-run with --replace to rebuild it (the old dashboard is deleted).

The personal API key (phx_...) can read your data -- unlike the public phc_
project key the apps use -- so it's only ever read from the environment, never
from a flag or a file. Scopes: insight:write, dashboard:write, query:read.

Dev tooling only: lives outside src/, so it never ships in the exe.
"""

import argparse
import os
import re
import sys

import httpx

DEFAULT_HOST = "https://us.posthog.com"
_SAFE_ENVIRONMENT = re.compile(r"^[A-Za-z0-9_-]+$")


class DashboardError(Exception):
    pass


def _sql(name, description, query):
    return {
        "name": name,
        "description": description,
        "query": {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": query}},
    }


def _trend(name, description, series, environment, breakdown=None, display="ActionsTable"):
    source = {
        "kind": "TrendsQuery",
        "series": series,
        "interval": "day",
        "dateRange": {"date_from": "-30d"},
        "properties": [
            {"key": "environment", "value": [environment], "operator": "exact", "type": "event"}
        ],
        "trendsFilter": {"display": display},
    }
    if breakdown:
        source["breakdownFilter"] = {"breakdown": breakdown, "breakdown_type": "event"}
    return {"name": name, "description": description, "query": {"kind": "InsightVizNode", "source": source}}


def _event(event, math="total", math_property=None, name=None):
    node = {"kind": "EventsNode", "event": event, "math": math, "name": name or event}
    if math_property:
        node["math_property"] = math_property
    return node


def build_tiles(environment):
    """The dashboard's insights, each scoped to ``environment``."""
    if not _SAFE_ENVIRONMENT.match(environment or ""):
        raise ValueError(f"environment must be letters, digits, - or _: {environment!r}")
    env = f"properties.environment = '{environment}'"

    return [
        _sql(
            "Q1 · Each recording: how long it took",
            "One row per recording. audio_min = length of the exam; transcribe/note/server = "
            "backend time; outcome note_pending means the note was finished later.",
            f"""SELECT timestamp,
       properties.exam_id AS exam,
       round(toFloat(properties.audio_duration_ms) / 60000, 1) AS audio_min,
       round(toFloat(properties.transcribe_ms) / 1000, 1) AS transcribe_s,
       round(toFloat(properties.note_gen_ms) / 1000, 1) AS note_s,
       round(toFloat(properties.total_ms) / 1000, 1) AS server_total_s,
       properties.outcome AS outcome,
       properties.source_app AS from_app
FROM events
WHERE event = 'soap_generated' AND {env}
ORDER BY timestamp DESC
LIMIT 200""",
        ),
        _trend(
            "Q1 · Vet's wait: Stop → note on screen (desktop)",
            "wait_ms from note_ready. via_offline_queue = true means it failed first and was retried.",
            [
                _event("note_ready", "median", "wait_ms", "median wait (ms)"),
                _event("note_ready", "p90", "wait_ms", "p90 wait (ms)"),
                _event("note_ready", "total", None, "notes"),
            ],
            environment,
            breakdown="via_offline_queue",
        ),
        _sql(
            "Q2 · Regenerations and edits per exam",
            "*_kept: 1.0 = box untouched, lower = more rewritten (lowest across saves).",
            f"""SELECT properties.exam_id AS exam,
       countIf(event = 'note_regenerated') AS regenerations,
       countIf(event = 'note_saved') AS saves,
       maxIf(toInt(properties.fields_changed_count), event = 'note_saved') AS most_boxes_changed,
       minIf(toFloat(properties.subjective_similarity), event = 'note_saved') AS subjective_kept,
       minIf(toFloat(properties.objective_similarity), event = 'note_saved') AS objective_kept,
       minIf(toFloat(properties.assessment_similarity), event = 'note_saved') AS assessment_kept,
       minIf(toFloat(properties.plan_similarity), event = 'note_saved') AS plan_kept
FROM events
WHERE event IN ('note_regenerated', 'note_saved') AND {env}
GROUP BY exam
ORDER BY regenerations DESC, saves DESC""",
        ),
        _sql(
            "Q2 · Which boxes he rewrites most",
            "Average share of each box changed per save (0 = never edited, 1 = fully rewritten).",
            f"""SELECT count() AS saves,
       round(avg(1 - toFloat(properties.subjective_similarity)), 3) AS subjective_changed,
       round(avg(1 - toFloat(properties.objective_similarity)), 3) AS objective_changed,
       round(avg(1 - toFloat(properties.assessment_similarity)), 3) AS assessment_changed,
       round(avg(1 - toFloat(properties.plan_similarity)), 3) AS plan_changed,
       round(avg(1 - toFloat(properties.transcript_similarity)), 3) AS transcript_changed
FROM events
WHERE event = 'note_saved' AND {env}""",
        ),
        _sql(
            "Q3 · AVImark calibrations",
            "recalibrations = calibrations started when one already existed.",
            f"""SELECT countIf(event = 'calibration_started') AS started,
       countIf(event = 'calibration_started' AND toString(properties.is_recalibration) = 'true') AS recalibrations,
       countIf(event = 'calibration_completed') AS completed,
       countIf(event = 'calibration_abandoned') AS abandoned,
       countIf(event = 'calibration_invalid') AS invalid_restarts
FROM events
WHERE event IN ('calibration_started', 'calibration_completed',
                'calibration_abandoned', 'calibration_invalid') AND {env}""",
        ),
        _sql(
            "Q4 · Inject taps from the phone, per exam",
            "inject_taps > 1 = he tried to inject the same note again.",
            f"""SELECT properties.exam_id AS exam,
       count() AS inject_taps,
       countIf(toString(properties.edited_before_inject) = 'true') AS taps_after_editing,
       min(timestamp) AS first_tap,
       max(timestamp) AS last_tap
FROM events
WHERE event = 'injection_requested' AND {env}
GROUP BY exam
ORDER BY inject_taps DESC""",
        ),
        _sql(
            "Q4 · How injects landed in AVImark",
            "result: per_box / single_block / single_block_fallback (stale calibration) / "
            "refused_* (no chart, several charts open, or AVImark wouldn't come to the front).",
            f"""SELECT properties.source AS source,
       properties.result AS result,
       count() AS injects
FROM events
WHERE event = 'injection_completed' AND {env}
GROUP BY source, result
ORDER BY injects DESC""",
        ),
        _sql(
            "Frustration signals",
            "Hotkey pressed while busy, failed notes, error/status pop-ups and crashes.",
            f"""SELECT countIf(event = 'hotkey_while_busy') AS hotkey_while_busy,
       countIf(event = 'note_failed') AS notes_failed,
       countIf(event = 'pending_note_gave_up') AS notes_given_up,
       countIf(event = 'flyout_shown' AND properties.kind = 'message') AS message_popups,
       countIf(event = '$exception') AS crashes
FROM events
WHERE event IN ('hotkey_while_busy', 'note_failed', 'pending_note_gave_up',
                'flyout_shown', '$exception') AND {env}""",
        ),
        _trend(
            "Activity per day",
            "Notes generated, saves, and inject taps from the phone.",
            [
                _event("soap_generated", name="notes generated"),
                _event("note_saved", name="saves"),
                _event("note_regenerated", name="regenerations"),
                _event("injection_requested", name="phone inject taps"),
            ],
            environment,
            display="ActionsLineGraph",
        ),
    ]


def dashboard_name(environment):
    return f"Vet Soap Notetaker ({environment})"


class PostHogApi:
    def __init__(self, personal_key, host=DEFAULT_HOST):
        self.host = host.rstrip("/")
        self._client = httpx.Client(
            base_url=f"{self.host}/api/projects/@current",
            headers={"Authorization": f"Bearer {personal_key}"},
            timeout=60,
        )

    def _call(self, method, path, **kwargs):
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail") or response.text
            except ValueError:
                detail = response.text
            raise DashboardError(f"{method} {path} -> {response.status_code}: {detail}")
        return response.json()

    def run_query(self, query):
        return self._call("POST", "/query/", json={"query": query})

    def dashboards(self):
        return self._call("GET", "/dashboards/", params={"limit": 200})["results"]

    def create_dashboard(self, name, description):
        return self._call("POST", "/dashboards/", json={"name": name, "description": description})

    def delete_dashboard(self, dashboard_id):
        return self._call("PATCH", f"/dashboards/{dashboard_id}/", json={"deleted": True})

    def create_insight(self, tile, dashboard_id):
        return self._call("POST", "/insights/", json={**tile, "dashboards": [dashboard_id]})


def create_dashboard(api, environment, replace=False, log=print):
    tiles = build_tiles(environment)
    name = dashboard_name(environment)

    existing = [d for d in api.dashboards() if d.get("name") == name]
    if existing and not replace:
        raise DashboardError(f"dashboard {name!r} already exists; re-run with --replace to rebuild it")

    # Check every query before creating anything, so a mistake can't leave a
    # half-built dashboard behind.
    for tile in tiles:
        try:
            api.run_query(tile["query"]["source"])
        except DashboardError as exc:
            raise DashboardError(f"query for {tile['name']!r} failed: {exc}") from exc
        log(f"  ok  {tile['name']}")

    for old in existing:
        api.delete_dashboard(old["id"])
        log(f"deleted the old {name!r} (id {old['id']})")

    dashboard = api.create_dashboard(
        name, f"Usage analytics for environment={environment} (built by tools/posthog_dashboard.py)"
    )
    for tile in tiles:
        api.create_insight(tile, dashboard["id"])
    return f"{api.host}/dashboard/{dashboard['id']}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--environment", required=True, help="e.g. test or demo")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"PostHog app host (default {DEFAULT_HOST})")
    parser.add_argument("--replace", action="store_true", help="delete and rebuild an existing dashboard")
    args = parser.parse_args(argv)

    key = os.environ.get("POSTHOG_PERSONAL_API_KEY", "")
    if not key:
        print("Set POSTHOG_PERSONAL_API_KEY to a personal API key (phx_...).", file=sys.stderr)
        return 2
    try:
        url = create_dashboard(PostHogApi(key, args.host), args.environment, replace=args.replace)
    except (DashboardError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Dashboard ready: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
