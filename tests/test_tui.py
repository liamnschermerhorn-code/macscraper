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


# ---- rejecting by hand ---------------------------------------------------------------------------------

def test_reject_remembers_undoes_and_keeps_your_place(tmp_path):
    from macscraper import cli, rejected

    store = tmp_path / "rejected.json"

    async def go():
        items = make_items()
        app = ResultsApp(items, set(), "", rejected_path=store)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#list")
            assert table.row_count == 3
            await pilot.press("down")                       # highlight the 2nd listing
            await pilot.pause()
            second = app.current()
            await pilot.press("x")
            await pilot.pause()
            assert second.verdict == "REJECT" and second.reasons[0].startswith("rejected by you")
            assert table.row_count == 2 and app.changed
            assert app.current() is not second              # moved on to the next listing, same row position
            assert table.cursor_row == 1
            data = rejected.load(store)
            assert list(data) == [second.key] and data[second.key]["was"] in ("MATCH", "POSSIBLE")
            assert data[second.key]["title"] == second.title

            await pilot.press("u")                          # undo
            await pilot.pause()
            assert second.verdict != "REJECT" and table.row_count == 3 and rejected.load(store) == {}

            await pilot.press("x")                          # reject again, then bring it back from the rejected view
            await pilot.press("r")
            await pilot.pause()
            assert table.row_count == 4                     # the detector's own reject + yours
            for it in app.visible():
                if it.key == second.key:
                    table.move_cursor(row=table.get_row_index(it.key))
            await pilot.pause()
            await pilot.press("x")                          # x on one you rejected = restore
            await pilot.pause()
            assert second.verdict != "REJECT" and rejected.load(store) == {}
            assert app.rejection_summary() == []        # nothing left rejected by you
    run(go())


def test_detectors_own_rejects_cannot_be_rejected_twice_and_nothing_crashes_when_empty(tmp_path):
    async def go():
        items = make_items()
        app = ResultsApp(items, set(), "", rejected_path=tmp_path / "r.json")
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("r")                          # show rejected
            await pilot.pause()
            table = app.query_one("#list")
            m1 = next(i for i in items if i.verdict == "REJECT")
            table.move_cursor(row=table.get_row_index(m1.key))
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            assert m1.verdict == "REJECT" and not app.changed and not (tmp_path / "r.json").exists()
        empty = ResultsApp([], set(), "", rejected_path=tmp_path / "e.json")
        async with empty.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.press("u")
    run(go())


def test_rejections_apply_to_the_next_run_and_summary_lists_them(tmp_path):
    from macscraper import cli, rejected

    store = tmp_path / "rejected.json"

    async def first_run():
        items = make_items()
        app = ResultsApp(items, set(), "", rejected_path=store)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            target = app.current()
            await pilot.press("x")
            await pilot.pause()
            return target.key, target.title, app.rejection_summary()

    key, title, summary = run(first_run())
    assert summary and title[:40] in summary[1] and "was" in summary[1]

    # next run: the same listing comes back from the sites, evaluated afresh, and is hidden again
    fresh = make_items()
    assert cli.apply_user_rejections(fresh, store) == 1
    hidden = next(i for i in fresh if i.key == key)
    assert hidden.verdict == "REJECT" and hidden.reasons[0].startswith("rejected by you")
    assert [i.key for i in fresh if i.verdict != "REJECT" and i.key == key] == []
    assert cli.apply_user_rejections(fresh, tmp_path / "missing.json") == 0

    # and the command line can add / remove by link
    rejected.add_url(store, "https://www.ebay.com/itm/999?hash=abc", "Intel")
    assert rejected.key_of("https://www.ebay.com/itm/999?hash=abc") in rejected.load(store)
    assert rejected.remove(store, "https://www.ebay.com/itm/999") is True
    assert rejected.remove(store, "https://www.ebay.com/itm/999") is False


# ---- click a column heading to sort --------------------------------------------------------------------

def sort_items():
    crit = Criteria(max_total=700)
    raw = [
        ("MacBook Air 13 M2 24GB 512GB", 420, "ebay"),
        ("MacBook Pro 14 M4 Pro 32GB 1TB", 690, "craigslist/chicago"),
        ("MacBook Air 15 M3 24GB 512GB", 560, "ebay"),
        ("MacBook Air 13 Midnight", 300, "reddit/appleswap"),        # chip and RAM not stated
        ("MacBook Pro 16 M3 Max 32GB 1TB", 400, "ebay"),
    ]
    items = [evaluate(Listing(source=s, title=t, url=f"https://x/{n}", price=p, shipping=0.0), crit) for n, (t, p, s) in enumerate(raw)]
    return [i for i in items if i.verdict != "REJECT"]


def heading_x(app, key):
    """Where to click to hit one column's heading (each column is its width + 2 cells of padding)."""
    x = 0
    for col_key, column in app.query_one("#list").columns.items():
        if col_key.value == key:
            return x + 3
        x += column.width + 2
    raise KeyError(key)


def test_clicking_a_heading_sorts_and_clicking_again_flips_it():
    async def go():
        items = sort_items()
        app = ResultsApp(items, set(), "")
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#list")
            start = [i.chip for i in app.visible()]

            await pilot.click("#list", offset=(heading_x(app, "chip"), 0))   # click "Chip"
            await pilot.pause()
            chips = [i.chip for i in app.visible()]
            assert chips == ["M4 Pro", "M3 Max", "M3", "M2", ""], chips      # highest at the top, unknown chip last
            assert "▼" in str(table.columns[list(table.columns)[2]].label)

            await pilot.click("#list", offset=(heading_x(app, "chip"), 0))   # again: highest at the bottom
            await pilot.pause()
            chips = [i.chip for i in app.visible()]
            assert chips == ["M2", "M3", "M3 Max", "M4 Pro", ""], chips       # highest at the bottom; unknown still last
            assert "▲" in str(table.columns[list(table.columns)[2]].label)

            await pilot.click("#list", offset=(heading_x(app, "chip"), 0))   # a third click: back to highest first
            await pilot.pause()
            assert app.sort_descending is True
            assert start != [i.chip for i in app.visible()]
    run(go())


def test_chip_order_variants_and_other_columns():
    from macscraper.tui import chip_rank, sort_listings

    assert chip_rank("M4 Pro") > chip_rank("M4") > chip_rank("M3 Max") > chip_rank("M3 Pro") > chip_rank("M3") > chip_rank("M2 Ultra") > chip_rank("M2")
    assert chip_rank("M2?") == chip_rank("M2") and chip_rank("") is None and chip_rank(None) is None

    async def go():
        items = sort_items()
        app = ResultsApp(items, set(), "")
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.pause()
            for key in ("total", "ram", "title", "source", "verdict"):
                await pilot.click("#list", offset=(heading_x(app, key), 0))
                await pilot.pause()
                assert app.sort_column == key
                rows = app.visible()
                if key == "total":
                    prices = [i.total for i in rows]
                    assert prices == sorted(prices, reverse=True)           # highest at the top first
                    await pilot.click("#list", offset=(heading_x(app, "total"), 0))
                    await pilot.pause()
                    prices = [i.total for i in app.visible()]
                    assert prices == sorted(prices)                          # flipped: highest at the bottom
                if key == "title":
                    names = [i.title.lower() for i in rows]
                    assert names == sorted(names)                            # text goes A-Z first
                if key == "ram":
                    rams = [i.ram_gb for i in rows if i.ram_gb]
                    assert rams == sorted(rams, reverse=True) and rows[-1].ram_gb is None   # unknown RAM last
            await pilot.press("3")                                           # keyboard: 3 = chip
            await pilot.pause()
            assert app.sort_column == "chip" and app.sort_descending is True
            await pilot.press("3")
            await pilot.pause()
            assert app.sort_descending is False
        # sorting never loses or duplicates anything
        assert sorted(i.key for i in app.visible()) == sorted(i.key for i in items)
    run(go())


def test_details_pane_shows_what_the_seller_wrote():
    items = make_items()
    items[0].description = "Clean machine, original owner. [photo text] Chip Apple M2 | Memory 24 GB"
    items[0].description_checked = True
    items[1].description_checked = False

    async def go():
        app = ResultsApp(items, set(), "")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            first = str(app.query_one("#details").render())
            assert "Seller's description:" in first and "Clean machine, original owner." in first
            assert "Chip Apple M2" not in first                    # text read from photos isn't passed off as the seller's words
            await pilot.press("down")
            await pilot.pause()
            assert "Description not read" in str(app.query_one("#details").render())
    run(go())
