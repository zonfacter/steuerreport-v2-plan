"""Controlled read-only review-panel loading, missing and retry regression."""
from __future__ import annotations

import json
from urllib.parse import urlparse

from playwright.sync_api import expect

from ux_workspace_fixtures import STAMP, WorkspaceFixture


def check_review_panel(browser, base_url, output):
    class ReviewFixture(WorkspaceFixture):
        def review_item(self):
            item = super().review_item()
            item["task"].update(category="reconciliation", asset="EUR", evidence_refs=["account:synthetic-account:asset:EUR"])
            item.update(account="synthetic-account", account_ref="a_" + "a" * 20, event_ids=[])
            return item

    fixture = ReviewFixture()
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors, screenshots, held, task_requests, external = [], [], [], [], []
    mode = "hold"
    page.on("pageerror", lambda error: errors.append(str(error)))

    def reply(route, items, status=200):
        fixture.send(route, dict(items=items, total=len(items), unfiltered_total=1, blocking_total=1,
                                 page=1, pages=1, page_size=25, generated_at=STAMP), status)

    def mock(route):
        if not route.request.url.startswith(base_url + "/"):
            external.append(route.request.url.split("?")[0])
            route.abort()
            return
        path = urlparse(route.request.url).path
        if not path.startswith("/api/"):
            route.continue_()
            return
        body = route.request.post_data_json if route.request.method == "POST" else {}
        assert route.request.method == "GET" or path in {"/api/v1/workspace/review/query", "/api/v1/activity/query"}
        if path == "/api/v1/workspace/review/query" and body.get("task_id"):
            task_requests.append(body)
            if mode == "hold":
                held.append(route)
                page.evaluate("window.__reviewRequestHeld = true")
            else:
                reply(route, [fixture.review_item()])
            return
        if not fixture.handle(route):
            fixture.send(route, {})

    context.route("**/*", mock)
    page.add_init_script("""(() => {
      window.__falseReviewStates = [];
      new MutationObserver(() => {
        const panel = document.querySelector('[role=dialog]');
        if (panel && /Aufgabe nicht in der aktuellen Seite|Prüfaufgabe nicht gefunden|Schließen und Liste aktualisieren/.test(panel.innerText)) {
          window.__falseReviewStates.push(panel.innerText);
        }
      }).observe(document, { childList: true, subtree: true, characterData: true });
    })();""")

    def loading():
        page.wait_for_function("window.__reviewRequestHeld === true")
        panel = page.get_by_role("dialog")
        expect(panel.get_by_text("Prüfaufgabe: Ladevorgang läuft.", exact=True)).to_be_visible()
        expect(panel.get_by_text("Prüfaufgabe nicht gefunden", exact=True)).to_have_count(0)
        expect(panel.get_by_role("button", name="Erneut versuchen", exact=True)).to_have_count(0)
        assert not page.evaluate("window.__falseReviewStates"), "Premature empty panel, even transiently"

    def snapshot(name):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / (name + ".png")), animations="disabled")
        screenshots.append(dict(file=name + ".png", viewport=page.viewport_size, route=page.url.split("#", 1)[-1], data="synthetic"))

    # Keep a deliberately nonmatching list filter: the task ID must resolve independently.
    page.goto(base_url + "/#review?category=price&status=high&size=10", wait_until="networkidle")
    expect(page.get_by_text("Keine passenden Aufgaben", exact=True)).to_be_visible()
    page.goto(base_url + "/#sources", wait_until="networkidle")
    page.get_by_role("button", name="Demo-Börse", exact=True).click()
    page.get_by_role("dialog").get_by_role("tab", name="Hinweise / Abgleich", exact=True).click()
    page.get_by_role("button", name="Review-Aufgabe öffnen", exact=True).click()
    loading()
    review_url = page.url
    assert "category=price" in review_url and "status=high" in review_url and "size=10" in review_url
    snapshot("R1-source-loading-1440")
    page.set_viewport_size({"width": 390, "height": 844})
    snapshot("R1-source-loading-390")
    reply(held.pop(), [fixture.review_item()])
    expect(page.get_by_role("dialog").get_by_role("heading", name="Originalbeleg prüfen", exact=True)).to_be_visible()
    assert task_requests[-1] == {"task_id": "review-demo"}
    assert not page.evaluate("window.__falseReviewStates")

    page.get_by_role("button", name="Bestehenden Prüfablauf öffnen", exact=True).click()
    expect(page.get_by_role("tab", name="Ledger", exact=True)).to_have_attribute("aria-selected", "true")
    page.evaluate("window.__reviewRequestHeld = false")
    page.get_by_role("button", name="Zur Review-Aufgabe zurück", exact=True).click()
    loading()
    assert page.url == review_url
    reply(held.pop(), [fixture.review_item()])
    expect(page.get_by_role("dialog").get_by_role("heading", name="Originalbeleg prüfen", exact=True)).to_be_visible()
    snapshot("R1-return-ready-390")

    # Navigate between pending IDs without a full page reload; an old reply must not win.
    page.evaluate("window.__reviewRequestHeld = false; location.hash = '#review?detail=review-old'")
    loading()
    old = held.pop()
    page.evaluate("window.__reviewRequestHeld = false; location.hash = '#review?detail=review-second'")
    loading()
    second = fixture.review_item()
    second["task"].update(task_id="review-second", title="Zweite synthetische Aufgabe")
    reply(held.pop(), [second])
    expect(page.get_by_role("dialog").get_by_role("heading", name="Zweite synthetische Aufgabe", exact=True)).to_be_visible()
    reply(old, [fixture.review_item()])
    expect(page.get_by_role("dialog").get_by_role("heading", name="Zweite synthetische Aufgabe", exact=True)).to_be_visible()

    page.evaluate("window.__reviewRequestHeld = false; location.hash = '#review?detail=review-missing'")
    loading()
    reply(held.pop(), [])
    expect(page.get_by_role("dialog").get_by_text("Prüfaufgabe nicht gefunden", exact=True)).to_be_visible()
    expect(page.get_by_role("dialog").get_by_role("alert")).to_have_count(0)
    snapshot("R1-missing-390")

    page.evaluate("window.__falseReviewStates = []; window.__reviewRequestHeld = false; location.hash = '#review?detail=review-demo'")
    loading()
    reply(held.pop(), [], 503)
    expect(page.get_by_role("dialog").get_by_role("alert")).to_be_visible()
    expect(page.get_by_role("dialog").get_by_text("Prüfaufgabe nicht gefunden", exact=True)).to_have_count(0)
    page.set_viewport_size({"width": 1440, "height": 1000})
    snapshot("R1-error-1440")
    page.evaluate("window.__reviewRequestHeld = false")
    page.get_by_role("dialog").get_by_role("button", name="Erneut versuchen", exact=True).click()
    loading()
    reply(held.pop(), [fixture.review_item()])
    expect(page.get_by_role("dialog").get_by_role("heading", name="Originalbeleg prüfen", exact=True)).to_be_visible()
    expect(page.get_by_role("dialog").get_by_role("alert")).to_have_count(0)
    snapshot("R1-retry-ready-1440")
    assert not held and not errors and not external
    result = dict(status="bestanden", source_entry_delayed=True, return_delayed=True, task_outside_list_filter=True,
                  filter_context_preserved=True, missing_only_after_success=True, error_distinct_with_retry=True,
                  task_switch_stale_reply_ignored=True, transient_false_states=0, all_api_responses_synthetic=True,
                  javascript_errors=errors, external_requests=external, screenshots=screenshots)
    (output / "review-panel-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    context.unroute_all(behavior="ignoreErrors")
    context.close()
    print("R1: Verzögerte ID-Abfrage, Rückweg, Leertreffer, Fehler/Wiederholen und Aufgabenwechsel bestanden.", flush=True)
    return result
