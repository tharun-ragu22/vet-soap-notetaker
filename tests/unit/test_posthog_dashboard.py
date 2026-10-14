import json

import httpx
import pytest
import respx

from tools import posthog_dashboard as dash

API = "https://us.posthog.com/api/projects/@current"


def test_every_tile_is_scoped_to_the_chosen_environment():
    tiles = dash.build_tiles("demo")

    assert len(tiles) >= 8
    for tile in tiles:
        source = tile["query"]["source"]
        if source["kind"] == "HogQLQuery":
            assert "properties.environment = 'demo'" in source["query"], tile["name"]
        else:
            assert {"key": "environment", "value": ["demo"], "operator": "exact", "type": "event"} in source["properties"], tile["name"]


def test_the_four_questions_each_have_a_tile():
    names = " ".join(tile["name"] for tile in dash.build_tiles("demo"))
    for question in ("Q1", "Q2", "Q3", "Q4"):
        assert question in names


@pytest.mark.parametrize("environment", ["demo'; DROP", "", "has space"])
def test_unsafe_environment_names_are_rejected(environment):
    with pytest.raises(ValueError):
        dash.build_tiles(environment)


def _mock_api(existing=(), query_status=200):
    respx.get(f"{API}/dashboards/").mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": i, "name": n} for i, n in existing], "next": None}
        )
    )
    query = respx.post(f"{API}/query/").mock(
        return_value=httpx.Response(query_status, json={"detail": "bad query"} if query_status != 200 else {"results": []})
    )
    create_dashboard = respx.post(f"{API}/dashboards/").mock(
        return_value=httpx.Response(201, json={"id": 42, "name": "x"})
    )
    create_insight = respx.post(f"{API}/insights/").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    return query, create_dashboard, create_insight


@respx.mock
def test_create_checks_every_query_then_builds_the_dashboard_and_its_tiles():
    query, create_dashboard, create_insight = _mock_api()
    client = dash.PostHogApi(personal_key="phx_test", host="https://us.posthog.com")

    url = dash.create_dashboard(client, "demo")

    tiles = dash.build_tiles("demo")
    assert query.call_count == len(tiles)
    assert create_dashboard.call_count == 1
    assert json.loads(create_dashboard.calls.last.request.content)["name"] == "Vet Soap Notetaker (demo)"
    assert create_insight.call_count == len(tiles)
    for call in create_insight.calls:
        assert json.loads(call.request.content)["dashboards"] == [42]
    assert query.calls.last.request.headers["Authorization"] == "Bearer phx_test"
    assert url == "https://us.posthog.com/dashboard/42"


@respx.mock
def test_a_failing_query_stops_before_anything_is_created():
    _, create_dashboard, create_insight = _mock_api(query_status=400)
    client = dash.PostHogApi(personal_key="phx_test", host="https://us.posthog.com")

    with pytest.raises(dash.DashboardError, match="bad query"):
        dash.create_dashboard(client, "demo")

    assert create_dashboard.call_count == 0
    assert create_insight.call_count == 0


@respx.mock
def test_an_existing_dashboard_is_kept_unless_replace_is_asked_for():
    _, create_dashboard, _ = _mock_api(existing=[(7, "Vet Soap Notetaker (demo)")])
    client = dash.PostHogApi(personal_key="phx_test", host="https://us.posthog.com")

    with pytest.raises(dash.DashboardError, match="already exists"):
        dash.create_dashboard(client, "demo")
    assert create_dashboard.call_count == 0


@respx.mock
def test_replace_deletes_the_old_dashboard_first():
    _, create_dashboard, _ = _mock_api(existing=[(7, "Vet Soap Notetaker (demo)")])
    delete = respx.patch(f"{API}/dashboards/7/").mock(return_value=httpx.Response(200, json={}))
    client = dash.PostHogApi(personal_key="phx_test", host="https://us.posthog.com")

    dash.create_dashboard(client, "demo", replace=True)

    assert json.loads(delete.calls.last.request.content) == {"deleted": True}
    assert create_dashboard.call_count == 1


def test_main_needs_the_personal_key_in_the_environment(monkeypatch, capsys):
    monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
    assert dash.main(["--environment", "demo"]) == 2
    assert "POSTHOG_PERSONAL_API_KEY" in capsys.readouterr().err
