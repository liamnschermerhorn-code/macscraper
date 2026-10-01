"""Live results screen. Unlike a printed table it reflows as the terminal window is resized:
the title column stretches, optional columns drop out when space runs short, and the detail
pane moves from beside the list to beneath it on narrow windows."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, Static

from . import rejected
from .models import Listing

VERDICT_STYLE = {"MATCH": "bold green", "POSSIBLE": "yellow", "REJECT": "dim red"}
NARROW_BELOW = 100  # window columns; narrower than this puts the details pane under the list
SHORT_SOURCE = {"ebay": "eBay", "reddit/appleswap": "Reddit"}


def short_source(source: str) -> str:
    if source.startswith("craigslist"):
        return "Craigslist"
    return SHORT_SOURCE.get(source, source)


class FitTable(DataTable):
    """A DataTable that tells the app its real width once the layout has settled, so columns are
    sized for the room the table actually has now (not the room it had before the resize)."""

    def on_resize(self, event: events.Resize) -> None:
        self.app.rebuild(event.size.width)


class ResultsApp(App):
    TITLE = "Mac deal hunt"
    CSS = """
    #body { layout: horizontal; height: 1fr; }
    #body.narrow { layout: vertical; }
    #list { width: 1fr; height: 1fr; }
    #details { width: 40%; min-width: 36; height: 1fr; padding: 0 1; border-left: tall $primary; overflow-y: auto; }
    #body.narrow #details { width: 100%; height: 11; border-left: none; border-top: tall $primary; }
    """
    BINDINGS = [
        Binding("o", "open", "Open link"),
        Binding("c", "copy", "Copy link"),
        Binding("m", "matches_only", "Matches only"),
        Binding("x", "reject", "Reject this"),
        Binding("u", "undo", "Undo reject"),
        Binding("r", "rejected", "Show rejected"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, items: list[Listing], new_keys: set[str], report: str = "", rejected_path: Path | None = None) -> None:
        super().__init__()
        self.items = items
        self.new_keys = new_keys
        self.report = report
        self.rejected_path = rejected_path  # where your rejections are remembered (None: not saved)
        self.changed = False                # you rejected or restored something this session
        self.undo_stack: list[Listing] = []
        self.matches_only = False
        self.show_rejected = False
        self.by_key: dict[str, Listing] = {}
        self.fit_width = 0

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="body"):
            yield FitTable(id="list", cursor_type="row", zebra_stripes=True)
            yield Static(id="details")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_layout(self.size.width)

    def on_resize(self, event: events.Resize) -> None:
        self._apply_layout(event.size.width)  # the table then reports its own new width (FitTable)

    def _apply_layout(self, width: int) -> None:
        self.query_one("#body").set_class(width < NARROW_BELOW, "narrow")

    # ------------------------------------------------------------------ table
    def visible(self) -> list[Listing]:
        out = []
        for it in self.items:
            if it.verdict == "REJECT" and not self.show_rejected:
                continue
            if self.matches_only and it.verdict != "MATCH":
                continue
            out.append(it)
        return out

    def rebuild(self, width: int | None = None) -> None:
        """(Re)draw the table to fit the room it currently has."""
        table = self.query_one("#list", DataTable)
        if width is None:
            width = self.fit_width or table.size.width or self.size.width
        self.fit_width = width
        keep = None
        if table.row_count:
            try:
                keep = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            except Exception:
                keep = None

        # (header, width) for the columns that always stay; extras appear as space allows.
        cols = [("", 10), ("Total", 6), ("Chip", 8), ("RAM", 4)]
        if width >= 70:
            cols.append(("Source", 10))
        title_w = max(14, width - sum(w + 2 for _, w in cols) - 4)

        table.clear(columns=True)
        for name, w in cols:
            table.add_column(name, width=w)
        table.add_column("Title", width=title_w)

        rows = self.visible()
        self.by_key = {}
        for it in rows:
            self.by_key[it.key] = it
            verdict = ("NEW " if it.key in self.new_keys and it.verdict != "REJECT" else "") + it.verdict
            cells = [
                Text(verdict[:10], style=VERDICT_STYLE.get(it.verdict, "")),
                f"${it.total:,.0f}" if it.total is not None else "?",
                it.chip or "?",
                f"{it.ram_gb}GB" if it.ram_gb else "?",
            ]
            if width >= 70:
                cells.append(short_source(it.source))
            title = it.title if len(it.title) <= title_w else it.title[: title_w - 1] + "…"
            cells.append(title)
            table.add_row(*cells, key=it.key)

        if keep and keep in self.by_key:
            table.move_cursor(row=table.get_row_index(keep))
        n_match = sum(i.verdict == "MATCH" for i in self.items)
        n_poss = sum(i.verdict == "POSSIBLE" for i in self.items)
        self.sub_title = (
            f"{len(rows)} shown · {n_match} match · {n_poss} possible"
            + (" · matches only" if self.matches_only else "")
            + (" · rejected shown" if self.show_rejected else "")
        )
        self._show_details()

    # ------------------------------------------------------------------ details
    def current(self) -> Listing | None:
        table = self.query_one("#list", DataTable)
        if not table.row_count:
            return None
        try:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            return None
        return self.by_key.get(key)

    def _show_details(self) -> None:
        pane = self.query_one("#details", Static)
        it = self.current()
        if it is None:
            pane.update(Text("Nothing to show with these filters.\n\nPress m or r to change them.", style="dim"))
            return
        t = Text()
        t.append(it.title + "\n", style="bold")
        t.append(it.verdict, style=VERDICT_STYLE.get(it.verdict, ""))
        if it.key in self.new_keys and it.verdict != "REJECT":
            t.append("  NEW", style="bold cyan")
        t.append("\n")
        price = f"${it.price:,.0f}" if it.price is not None else "price ?"
        if it.shipping:
            price += f" + ${it.shipping:,.0f} shipping"
        elif it.shipping == 0:
            price += " (no shipping cost)"
        else:
            price += " + shipping unknown"
        t.append(price + "\n")
        t.append(f"{it.chip or 'chip ?'} · {str(it.ram_gb) + 'GB' if it.ram_gb else 'RAM ?'} · {short_source(it.source)}")
        if it.location:
            t.append(f" · {it.location}")
        t.append("\n")
        if it.condition:
            t.append(f"Condition: {it.condition}\n", style="dim")
        for r in it.reasons:
            t.append("• " + r + "\n", style="bold yellow" if r.startswith("!!") else "")
        t.append("\n")
        t.append(it.url, style=f"underline link {it.url}")
        pane.update(t)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._show_details()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open()

    # ------------------------------------------------------------------ rejecting by hand
    def _reject(self, it: Listing) -> None:
        it.meta["orig"] = (it.verdict, list(it.reasons), it.score)
        it.meta["user_rejected"] = True
        was = it.verdict
        it.verdict, it.reasons, it.score = "REJECT", [f"rejected by you (was {was})"], -100
        rejected.add(self.rejected_path, it, was)

    def _restore(self, it: Listing) -> None:
        it.verdict, it.reasons, it.score = it.meta.pop("orig")
        it.meta.pop("user_rejected", None)
        rejected.remove(self.rejected_path, it.key)

    def _redraw_keeping_place(self, row: int) -> None:
        self.rebuild()
        table = self.query_one("#list", DataTable)
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        self._show_details()

    def action_reject(self) -> None:
        """Reject the highlighted listing (the detector missed that it's wrong). Press again on a listing
        you rejected earlier (view them with r) to bring it back."""
        it = self.current()
        table = self.query_one("#list", DataTable)
        if it is None:
            return
        row = table.cursor_row
        if it.meta.get("user_rejected"):
            self._restore(it)
            self.notify("Restored")
        elif it.verdict == "REJECT":
            self.notify(f"The detector already rejected this: {it.reasons[0] if it.reasons else ''}")
            return
        else:
            self._reject(it)
            self.undo_stack.append(it)
            self.notify("Rejected - it won't come back. Press u to undo.")
        self.changed = True
        self._redraw_keeping_place(row)

    def action_undo(self) -> None:
        while self.undo_stack:
            it = self.undo_stack.pop()
            if it.meta.get("user_rejected"):
                self._restore(it)
                self.changed = True
                self.rebuild()
                table = self.query_one("#list", DataTable)
                if it.key in self.by_key:
                    table.move_cursor(row=table.get_row_index(it.key))
                self.notify("Restored")
                return
        self.notify("Nothing to undo")

    def rejection_summary(self) -> list[str]:
        """What you rejected this session, for pasting back to improve the detector."""
        mine = [i for i in self.items if i.meta.get("user_rejected") and i.meta.get("orig")]
        if not mine:
            return []
        lines = [f"You rejected {len(mine)} listing(s) (saved in {self.rejected_path}):"]
        for i in mine:
            lines.append(f"  was {i.meta['orig'][0]:<8} {i.title[:90]}  {i.url}")
        return lines

    # ------------------------------------------------------------------ actions
    def action_open(self) -> None:
        if it := self.current():
            webbrowser.open(it.url)
            self.notify("Opened in your browser")

    def action_copy(self) -> None:
        if it := self.current():
            self.copy_to_clipboard(it.url)
            self.notify("Link copied")

    def action_matches_only(self) -> None:
        self.matches_only = not self.matches_only
        self.rebuild()

    def action_rejected(self) -> None:
        self.show_rejected = not self.show_rejected
        self.rebuild()
