"""IOM DTM Sudan snapshots -> movement_patterns totals + displacement_breakdown cells.

WHAT MAKES THIS LOADER UNUSUAL is that one payload writes two tables. The
totals are ordinary MovementPattern rows; the origin x destination matrix
behind each total is a different shape and goes to its own table. Both writes
happen inside load()'s single transaction, using the two escape hatches
loaders/base.py documents: _insert_rows for rows that are not all model fields,
after_insert for work that needs those rows to exist.

EVERYTHING IS ANCHORED ON HXL TAGS. Sheet names drift between snapshots -
001 says 'IDP MASTER LIST (ADMIN1)', 002 onwards say 'IDPs Masterlist (ADMIN1)'
- and header rows sit at different offsets. Worse, snapshot 004's IDP sheets
are TITLED 'Return Master List', a publisher slip. So kind comes from
'+idps+' vs '+rets+' in the HXL row and from nothing else.
"""
from datetime import datetime

from external_data.loaders import register
from external_data.loaders.base import Loader
from external_data.models import DisplacementBreakdown, MovementPattern

# The two formats DTM's A1 title uses. Between them they resolve all 32 sheets
# across the eight published snapshots.
DATE_FORMATS = ("%d-%b-%Y", "%d/%m/%Y")

# Header cells that are a breakdown but not a state of origin.
OUTSIDE = "Returned from outside Sudan"
NATIONALITY = {"SUDANESE": "SUDANESE", "NON SUDANESE": "NON_SUDANESE"}
# Never a breakdown: the returnee sheets restate their own total in a last column.
IGNORED_HEADERS = {"Total", ""}


def parse_sheet_date(title):
    """The reference date out of a sheet's A1 title.

    NO FILENAME FALLBACK, deliberately. Snapshot 006's filename begins
    `2026_24_05_`, which is ambiguous between 24 May and a year-month-day
    reading, so a fallback would encode a guess. An unreadable date is a reason
    to stop, not to invent one - a silently misdated row is indistinguishable
    from real data once it is in the table.
    """
    for token in str(title or "").replace(",", " ").split():
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(token, fmt).date()
            except ValueError:
                continue
    raise ValueError(
        f"no parseable date in sheet title {title!r}. Expected one of "
        f"{DATE_FORMATS} - e.g. '30-Jul-2026' or '31/3/2026'.")


def _number(value, where):
    """A breakdown cell as an int. A publisher's placeholder is an error.

    Coercing 'n/a' to 0 would turn a placeholder into a reconciliation failure
    whose message points at a different column entirely.
    """
    if value in (None, ""):
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}: expected a number, got {value!r}")
    return int(value)


def _hxl_row(rows):
    """Index of the HXL row, or None if this sheet is not a masterlist.

    This is also how the 'Read Me' tab is skipped, without naming it.
    """
    for index, row in enumerate(rows):
        for cell in row:
            if isinstance(cell, str) and cell.strip().startswith("#affected+"):
                return index
    return None


@register
class DtmSnapshotLoader(Loader):
    """One 'Displacement and Return Snapshot' workbook."""

    dataset = "displacement_snapshot"
    source = "dtm"
    model = MovementPattern
    tool = "package_show + xlsx"
    unique_fields = ["source", "metric", "iso3", "admin_pcode", "place_name",
                     "date", "population_group"]
    update_fields = ["admin_level", "value", "unit", "source_dataset",
                     "reference_period_start", "reference_period_end", "lat", "lon"]

    # ---- pass one -------------------------------------------------------
    def _state_codes(self, sheets):
        """{'Aj Jazirah': 'SD15', ...}, harvested from whichever admin1 sheets exist.

        THE 18 NAMES ARE NEVER HARDCODED. The admin2 sheets label their
        breakdown columns with state NAMES and carry no codes for them; only
        the admin1 sheets hold the pairs. A workbook that renamed a state
        therefore still resolves, and one that dropped its admin1 sheets fails
        loudly instead of writing every total with an empty matrix.
        """
        codes = {}
        for rows in sheets.values():
            hxl_at = _hxl_row(rows)
            if hxl_at is None:
                continue
            hxl = [str(c).strip() if c else "" for c in rows[hxl_at]]
            if "#adm1+name" not in hxl or "#adm1+pcode" not in hxl:
                continue
            # An admin2 sheet also carries both tags, and its adm1 columns are
            # still the state's name and code - so it is just as good a source.
            name_at, code_at = hxl.index("#adm1+name"), hxl.index("#adm1+pcode")
            for row in rows[hxl_at + 1:]:
                if len(row) > max(name_at, code_at) and row[name_at] and row[code_at]:
                    codes[str(row[name_at]).strip()] = str(row[code_at]).strip()
        if not codes:
            raise ValueError(
                "no state name->pcode pairs in this workbook: no sheet carried "
                "both #adm1+name and #adm1+pcode. Without them every breakdown "
                "column is unrecognised and the matrix would be silently empty.")
        return codes

    # ---- pass two -------------------------------------------------------
    def parse(self, payload, iso3, context=None):
        sheets = payload.get("sheets") or {}
        codes = self._state_codes(sheets)
        resource_id = (context or {}).get("resource_id", "")

        out = []
        for name, rows in sheets.items():
            hxl_at = _hxl_row(rows)
            if hxl_at is None:
                continue
            out.extend(self._parse_sheet(name, rows, hxl_at, codes, iso3, resource_id))
        return out

    def _parse_sheet(self, name, rows, hxl_at, codes, iso3, resource_id):
        hxl = [str(c).strip() if c else "" for c in rows[hxl_at]]
        header = [str(c).strip() if c else "" for c in rows[hxl_at - 1]]

        # Kind from the TAG, never the title - snapshot 004's IDP sheets are
        # titled 'Return Master List'.
        rets = any("+rets+" in tag for tag in hxl)
        metric = "returnees" if rets else "idps"
        dimension = "displaced_in" if rets else "origin"

        level = 2 if "#adm2+pcode" in hxl else 1
        pcode_at = hxl.index(f"#adm{level}+pcode")
        name_at = hxl.index(f"#adm{level}+name") if f"#adm{level}+name" in hxl else None
        ind_at = next(i for i, t in enumerate(hxl) if t.endswith("+ind"))
        hh_at = next(i for i, t in enumerate(hxl) if t.endswith("+hh"))

        title = next((c for c in rows[0] if c), "") if rows else ""
        on = parse_sheet_date(title)

        # Breakdown columns are everything right of the households column.
        breakdown_at = {}
        for column in range(hh_at + 1, len(header)):
            label = header[column]
            if label in IGNORED_HEADERS:
                continue
            if label == OUTSIDE:
                breakdown_at[column] = (dimension, "OUTSIDE_SDN")
            elif label in NATIONALITY:
                breakdown_at[column] = ("nationality", NATIONALITY[label])
            elif label in codes:
                breakdown_at[column] = (dimension, codes[label])
            # Anything else is left alone; the invariant below is what notices.

        out = []
        for row in rows[hxl_at + 1:]:
            if len(row) <= pcode_at or not row[pcode_at]:
                continue
            pcode = str(row[pcode_at]).strip()
            where = f"{name} {pcode}"
            total = _number(row[ind_at] if len(row) > ind_at else None, f"{where} total")
            households = _number(row[hh_at] if len(row) > hh_at else None, f"{where} HHs")

            cells = []
            for column, (dim, key) in breakdown_at.items():
                value = _number(row[column] if len(row) > column else None,
                                f"{where} column {header[column]!r}")
                if value:
                    cells.append({"dimension": dim, "key": key, "value": value})

            self._check(where, metric, dimension, total, cells)

            cells.append({"dimension": "households", "key": "total",
                          "value": households})

            place = (str(row[name_at]).strip()
                     if name_at is not None and len(row) > name_at and row[name_at]
                     else None)
            out.append({
                "date": on, "iso3": iso3,
                "admin_pcode": pcode, "admin_level": level, "place_name": place,
                "metric": metric, "population_group": metric,
                "value": total, "unit": "individuals",
                "source": self.source, "source_dataset": "iom-dtm-snapshot",
                "reference_period_start": None, "reference_period_end": on,
                "lat": None, "lon": None,
                "_breakdown": cells, "_resource_id": resource_id,
            })

        # A SHEET OF NOTHING IS A BROKEN FILE, NOT AN EMPTY ONE. openpyxl with
        # data_only=True returns None for a formula whose value was never
        # cached - a workbook re-saved by a non-Excel tool does this to every
        # cell - and _number turns None into 0. A sheet of zeros then satisfies
        # every invariant (0 == 0), and because it still produces p-code-bearing
        # rows, load()'s EmptyPayload never fires either. The result would be
        # 76 localities silently upserted to zero over good figures.
        #
        # One state legitimately reporting zero is ordinary; an entire
        # masterlist reporting zero is not - DTM does not publish a sheet to
        # say nobody is anywhere.
        if out and not any(r["value"] for r in out):
            raise ValueError(
                f"{name}: every one of its {len(out)} rows has a total of 0. "
                "That is not a published figure - it is what an uncomputed "
                "workbook looks like (openpyxl reads an uncached formula as "
                "None). Nothing was loaded; check the file.")
        return out

    def _check(self, where, metric, dimension, total, cells):
        """The published arithmetic, asserted.

        All three hold exactly across all eight snapshots - 2,272 rows, zero
        mismatches - so a break means the publisher changed the layout, and
        the honest response is to stop. A renamed or added breakdown column
        would otherwise lose a column's worth of people in silence.
        """
        parts = sum(c["value"] for c in cells if c["dimension"] == dimension)
        if parts != total:
            raise ValueError(
                f"{where}: {dimension} columns sum to {parts:,} but the stated "
                f"{metric} total is {total:,}. A breakdown column was renamed, "
                f"added or dropped.")
        nationality = [c for c in cells if c["dimension"] == "nationality"]
        if nationality:
            named = sum(c["value"] for c in nationality)
            if named != total:
                raise ValueError(
                    f"{where}: SUDANESE + NON SUDANESE = {named:,} but the "
                    f"stated total is {total:,}.")

    # ---- the two-table write --------------------------------------------
    def _insert_rows(self, rows):
        """MovementPattern objects, with this loader's private keys removed."""
        return [self.model(**{k: v for k, v in row.items()
                              if not k.startswith("_")}) for row in rows]

    def after_insert(self, rows):
        """The matrix cells, inside load()'s transaction.

        load() pops only `_geometry`, so `_breakdown` is still here. A failure
        writing these rolls the totals back too: one file is one transaction.

        EACH GROUP IS SWEPT BEFORE IT IS WRITTEN, and an upsert alone would be
        wrong. A revised snapshot that moves people from one origin to another
        names the new origin and simply stops naming the old one - so an
        upsert-only write leaves the old cell standing, `from` sums past the
        published total, and the popup lists an origin DTM has withdrawn.
        Nothing would notice: _check validates the PAYLOAD, never the table.

        The sweep is keyed on (metric, dest_pcode, date) - the group one sheet
        row owns - so a re-load of July cannot touch June.
        """
        groups = {(row["metric"], row["admin_pcode"], row["date"]) for row in rows}
        for metric, pcode, on in groups:
            DisplacementBreakdown.objects.filter(
                source=self.source, metric=metric, iso3=rows[0]["iso3"],
                dest_pcode=pcode, date=on).delete()

        cells = [
            DisplacementBreakdown(
                date=row["date"], iso3=row["iso3"], metric=row["metric"],
                dest_pcode=row["admin_pcode"], dest_level=row["admin_level"],
                dimension=cell["dimension"], key=cell["key"], value=cell["value"],
                source=self.source, source_dataset="iom-dtm-snapshot",
            )
            for row in rows for cell in row.get("_breakdown", [])
        ]
        if cells:
            DisplacementBreakdown.objects.bulk_create(
                cells, update_conflicts=True,
                unique_fields=["source", "metric", "iso3", "dest_pcode", "date",
                               "dimension", "key"],
                update_fields=["value", "dest_level", "source_dataset"],
            )

    def high_water(self, rows):
        return max((r["date"] for r in rows if r["date"]), default=None)

    def known_ids(self, rows):
        """The resources now held. This, not a date, is what narrows the next pull."""
        return [r["_resource_id"] for r in rows if r.get("_resource_id")]
