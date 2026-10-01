import argparse
from pathlib import Path
import os
import time

from macscraper import cli
from macscraper.filters import Criteria, evaluate
from macscraper.sources import facebook

CARDS = """
<html><body><div role="main">
<a href="/marketplace/item/1111111111111/?ref=search&referral_code=x">
  <img alt="Apple MacBook Air M2 24GB in Oak Park, IL" src="https://scontent.fbcdn.net/v/t45/aaa.jpg">
  <span>$650</span><span>$720</span><span>Apple MacBook Air M2 24GB 512GB</span><span>Oak Park, IL</span>
</a>
<a href="https://www.facebook.com/marketplace/item/2222222222222/">
  <span>$1,250</span><span>Just listed</span><span>MacBook Pro 14 M3 Pro 36GB</span><span>Chicago, IL</span>
</a>
<a href="/marketplace/item/3333333333333/"><span>Free</span><span>MacBook Pro 2015 box only</span><span>Gary, IN</span></a>
<a href="/marketplace/item/1111111111111/?ref=other"><span>$650</span><span>Apple MacBook Air M2 24GB 512GB</span></a>
<a href="/marketplace/item/4444444444444/"><img alt="MacBook Air 13 in Munster, IN" src="https://scontent.fbcdn.net/b.jpg"><span>$300</span></a>
<a href="/marketplace/category/computers">Computers</a>
<a href="/marketplace/item/5555555555555/"><span>$500</span></a>
</div></body></html>
"""

EMBEDDED = ('<html><script type="application/json">{"require":[{"__typename":"GroupCommerceProductItem","id":"7777777777777",'
            '"marketplace_listing_title":"MacBook Air M2 24GB 1TB \\u2013 like new","listing_price":{"formatted_amount":"$590",'
            '"amount":"590.00","currency":"USD"},"location":{"reverse_geocode":{"city":"Hammond","state":"IN"}},'
            '"primary_listing_photo":{"image":{"uri":"https:\\/\\/scontent.fbcdn.net\\/p.jpg"}}},'
            '{"__typename":"GroupCommerceProductItem","id":"1111111111111","marketplace_listing_title":"Apple MacBook Air M2 24GB 512GB",'
            '"listing_price":{"amount":"650.00"}}]}</script></html>')


def test_visible_cards():
    items = {i.url.split("/")[-2]: i for i in facebook.parse_cards(CARDS)}
    assert set(items) == {"1111111111111", "2222222222222", "3333333333333", "4444444444444"}   # no category link, no title-less card
    a = items["1111111111111"]
    assert (a.title, a.price, a.location, a.source) == ("Apple MacBook Air M2 24GB 512GB", 650.0, "Oak Park, IL", "facebook")
    assert a.url == "https://www.facebook.com/marketplace/item/1111111111111/"      # no tracking junk in the link
    assert a.shipping == 0.0 and a.negotiable and a.images == ["https://scontent.fbcdn.net/v/t45/aaa.jpg"]
    assert items["2222222222222"].title == "MacBook Pro 14 M3 Pro 36GB" and items["2222222222222"].price == 1250.0   # "Just listed" skipped
    assert items["3333333333333"].price == 0.0
    assert items["4444444444444"].title == "MacBook Air 13" and items["4444444444444"].price == 300.0               # title from the photo's alt text


def test_embedded_data_fills_gaps_and_adds_missing_listings():
    emb = {i.url.split("/")[-2]: i for i in facebook.parse_embedded(EMBEDDED)}
    assert emb["7777777777777"].title == "MacBook Air M2 24GB 1TB – like new"                 # – decoded
    assert emb["7777777777777"].price == 590.0 and emb["7777777777777"].location == "Hammond, IN"
    assert emb["7777777777777"].images == ["https://scontent.fbcdn.net/p.jpg"]
    both = {i.url.split("/")[-2]: i for i in facebook.parse_page(CARDS + EMBEDDED)}
    assert "7777777777777" in both and len(both) == 5                                         # embedded-only one added, no duplicates
    assert both["1111111111111"].price == 650.0


def test_files_folders_age_and_empty_pages(tmp_path):
    (tmp_path / "search1.html").write_text(CARDS)
    sub = tmp_path / "more"
    sub.mkdir()
    (sub / "search2.htm").write_text(EMBEDDED)
    (tmp_path / "notes.txt").write_text("ignore me")
    (tmp_path / "empty.html").write_text("<html><body>Marketplace - nothing here</body></html>")
    old = time.time() - 3 * 86400
    os.utime(tmp_path / "search1.html", (old, old))
    logs = []
    items = facebook.load([tmp_path], lambda *a, **k: logs.append(" ".join(map(str, a))))
    assert len({i.key for i in items}) == len(items) == 5                                     # duplicates across files collapse
    aged = next(i for i in items if i.key.endswith("2222222222222/"))                          # only in the 3-day-old file
    assert "saved 3 days ago" in aged.condition
    assert not next(i for i in items if i.key.endswith("7777777777777/")).condition            # fresh file: no warning
    both = next(i for i in items if i.key.endswith("1111111111111/"))                          # in the old AND the fresh file
    assert not both.condition                                                                  # the fresh snapshot wins
    assert any("empty.html: no listings found" in line and "Webpage, Complete" in line for line in logs)
    assert facebook.load([tmp_path / "missing"]) == [] and facebook.load([]) == []


def test_saved_listings_are_judged_like_everything_else(tmp_path, monkeypatch):
    (tmp_path / "s.html").write_text(CARDS + EMBEDDED)
    args = argparse.Namespace(sources="", cl_sites=None, deep=False, ocr=False, import_paths=[str(tmp_path)], out=str(tmp_path / "out"))
    items = cli.collect(args, {}, Criteria(max_total=700))
    by = {i.title: i for i in items}
    assert by["Apple MacBook Air M2 24GB 512GB"].verdict == "MATCH"            # $650, M2, 24GB, local pickup
    assert by["MacBook Air M2 24GB 1TB – like new"].verdict == "MATCH"
    assert by["MacBook Pro 14 M3 Pro 36GB"].verdict == "REJECT"                # 36GB isn't wanted (and $1,250)
    assert by["MacBook Pro 2015 box only"].verdict == "REJECT"
    assert by["MacBook Air 13"].verdict == "POSSIBLE"                          # no chip/RAM named: ask the seller
    assert all(i.source == "facebook" for i in items)


# ---- the startup conversation ---------------------------------------------------------------------------

def test_dragged_in_paths_are_understood(tmp_path):
    spaced = tmp_path / "My Saved Search (1).html"
    assert facebook.dropped_paths(str(spaced).replace(" ", "\\ ").replace("(", "\\(").replace(")", "\\)") + " ") == [spaced]  # Terminal / Ghostty escape
    assert facebook.dropped_paths(f"'{spaced}'") == [spaced] and facebook.dropped_paths(f'"{spaced}"') == [spaced]
    a, b = tmp_path / "a.html", tmp_path / "b b.html"
    assert facebook.dropped_paths(f"{a} {str(b).replace(' ', chr(92) + ' ')} ") == [a, b]                                 # two files at once
    assert facebook.dropped_paths(f"file://{str(spaced).replace(' ', '%20')}") == [spaced]
    assert str(facebook.dropped_paths("~/x.html")[0]).endswith("/x.html") and "~" not in str(facebook.dropped_paths("~/x.html")[0])
    assert facebook.dropped_paths("it's broken") == [Path("it's broken")]                                                  # unbalanced quote: no crash


def run_prompt(tmp_path, typed, say_yes=True):
    """Play the startup conversation with scripted answers; returns (saved paths, what was printed, urls opened)."""
    said, opened, answers = [], [], iter(typed)
    saved = cli.prompt_facebook(
        Criteria(max_total=700), ask=lambda q, d: say_yes, say=lambda *a, **k: said.append(" ".join(map(str, a))),
        open_url=opened.append, read=lambda prompt: next(answers, ""),
    )
    return saved, "\n".join(said), opened


def test_startup_conversation(tmp_path):
    good = tmp_path / "search one.html"
    good.write_text(CARDS)
    empty = tmp_path / "empty.html"
    empty.write_text("<html>nothing</html>")
    esc = lambda p: str(p).replace(" ", "\\ ")
    saved, said, opened = run_prompt(tmp_path, [esc(good) + " ", str(tmp_path / "typo.html"), esc(empty), ""])
    assert saved == [str(good)]                                              # only the file that had listings is kept
    assert len(opened) == 4 and all("facebook.com/marketplace/chicago/search" in u and "maxPrice=775" in u for u in opened)
    assert "search one.html: 4 listings" in said and "couldn't find" in said and "empty.html: no listings" in said
    assert "Webpage, Complete" in said and "scroll to the very bottom" in said and "Got 1 saved page" in said

    saved, said, opened = run_prompt(tmp_path, [""])                         # opens the searches, then Enter straight away
    assert saved == [] and len(opened) == 4 and "No pages added" in said
    saved, said, opened = run_prompt(tmp_path, ["whatever"], say_yes=False)  # answered "no": nothing opened, nothing asked
    assert saved == [] and opened == [] and said == ""


def test_dropped_files_reach_the_run_and_the_folder_still_counts(tmp_path, monkeypatch):
    f = tmp_path / "dropped.html"
    f.write_text(CARDS)
    folder = tmp_path / "marketplace"
    folder.mkdir()
    (folder / "older.html").write_text(EMBEDDED)
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(sources="", cl_sites=None, deep=False, ocr=False, import_paths=[str(f)], out=str(tmp_path / "out"))
    items = cli.collect(args, {}, Criteria(max_total=700))
    titles = {i.title for i in items}
    assert "Apple MacBook Air M2 24GB 512GB" in titles and "MacBook Air M2 24GB 1TB – like new" in titles   # dropped file + folder
