import asyncio

from macscraper.filters import Criteria, evaluate
from macscraper.models import Listing
from macscraper.tui import ResultsApp


def make_items():
    raw = [
        Listing(source="ebay", title="Apple MacBook Air 13.6 M2 24GB RAM 512GB SSD Midnight excellent condition", url="https://www.ebay.com/itm/111", price=480, shipping=0),
        Listing(source="craigslist/chicago", title="Mac mini M2 Pro 32GB 512GB", url="https://chicago.craigslist.org/x/222.html", price=450, shipping=0, location="oak park"),
        Listing(source="reddit/appleswap", title="MacBook Air M2 24GB/512GB", url="https://redd.it/abc", price=499),
        Listing(source="ebay", title="MacBook Air M1 16GB", url="https://www.ebay.com/itm/333", price=400, shipping=0),
    ]
    return [evaluate(i, Criteria(max_total=500)) for i in raw]


def run(coro):
    return asyncio.run(coro)


def test_layout_reflows_when_the_window_is_resized():
    async def go():
        app = ResultsApp(make_items(), set(), "")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            body = app.query_one("#body")
            table = app.query_one("#list")
            assert not body.has_class("narrow")
            wide_cols = len(table.columns)
            wide_title = table.columns[list(table.columns)[-1]].width

            await pilot.resize_terminal(60, 24)
            await pilot.pause()
            assert body.has_class("narrow")                      # details pane moved beneath the list
            assert len(table.columns) < wide_cols                # the Source column dropped out
            assert table.columns[list(table.columns)[-1]].width < wide_title  # title shrank to fit

            await pilot.resize_terminal(200, 50)
            await pilot.pause()
            assert not body.has_class("narrow")
            assert table.columns[list(table.columns)[-1]].width > wide_title  # and grew back, wider than before
    run(go())


def test_filters_and_actions(monkeypatch):
    opened = []
    monkeypatch.setattr("macscraper.tui.webbrowser.open", lambda url: opened.append(url))

    async def go():
        items = make_items()
        app = ResultsApp(items, {items[0].key}, "")
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#list")
            shown = table.row_count
            assert shown == 3                                    # the M1 listing is rejected, so hidden
            await pilot.press("r")
            await pilot.pause()
            assert table.row_count == 4                          # rejected shown on request
            await pilot.press("r")
            await pilot.press("m")
            await pilot.pause()
            assert table.row_count < shown                       # matches only
            await pilot.press("m")
            await pilot.pause()
            await pilot.press("o")                               # open the highlighted listing
            assert opened and opened[0].startswith("http")
            details = str(app.query_one("#details").render())
            assert opened[0] in details                          # the full link is always shown
    run(go())


def test_empty_results_do_not_crash():
    async def go():
        app = ResultsApp([], set(), "")
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.query_one("#list").row_count == 0
    run(go())
