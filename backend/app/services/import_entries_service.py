"""Entry import logic — extracted from ImportService for 300-line rule."""

import csv
import json
from datetime import date as date_type
from io import StringIO

from app.metric_helpers import insert_value


class EntryImporter:
    """Handles importing entries and auxiliary data (AW, notes) from ZIP."""

    def __init__(self, repo, conn) -> None:
        self.repo = repo
        self.conn = conn

    async def import_entries(
        self, zip_file, slug_to_id: dict, slug_to_type: dict,
    ) -> tuple[int, int, list[str]]:
        imported = 0
        skipped = 0
        errors: list[str] = []

        all_metric_ids = list(slug_to_id.values())
        slot_lookup = await self.repo.get_slot_lookup(all_metric_ids)

        text = zip_file.read('entries.csv').decode('utf-8')
        reader = csv.DictReader(StringIO(text))

        for row_num, row in enumerate(reader, start=2):
            try:
                slug = row.get('metric_slug', '')
                metric_id = slug_to_id.get(slug)
                if not metric_id or slug_to_type.get(slug) in ("computed", "text"):
                    skipped += 1
                    continue

                d = date_type.fromisoformat(row['date'])
                slot_id = self._resolve_slot_id(row, metric_id, slot_lookup)
                if slot_id is None and row.get('slot_sort_order', '') not in ('', None):
                    try:
                        so = int(row['slot_sort_order'])
                        label = row.get('slot_label', '') or f'Slot {so}'
                        new_sid = await self.repo.find_or_create_slot(label)
                        await self.repo.insert_metric_slot_on_fly(metric_id, new_sid, so)
                        slot_lookup[metric_id][so] = new_sid
                        slot_id = new_sid
                    except (ValueError, TypeError):
                        pass

                if await self.repo.check_entry_duplicate(metric_id, d, slot_id):
                    skipped += 1
                    continue

                mt = slug_to_type.get(slug, "bool")
                value = json.loads(row.get('value', 'false'))
                value = await self._coerce_value(value, mt, metric_id)
                if value is None:
                    skipped += 1
                    continue

                async with self.conn.transaction():
                    entry_id = await self.repo.create_entry(metric_id, d, slot_id)
                    await insert_value(self.conn, entry_id, value, mt, entry_date=d, metric_id=metric_id)
                imported += 1
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")
                skipped += 1

        return imported, skipped, errors

    async def import_aw_data(self, zip_file) -> None:
        if 'aw_daily.csv' in zip_file.namelist():
            text = zip_file.read('aw_daily.csv').decode('utf-8')
            for row in csv.DictReader(StringIO(text)):
                d = date_type.fromisoformat(row['date'])
                await self.repo.upsert_aw_daily(d, int(row['total_seconds']), int(row['active_seconds']))
        if 'aw_apps.csv' in zip_file.namelist():
            text = zip_file.read('aw_apps.csv').decode('utf-8')
            for row in csv.DictReader(StringIO(text)):
                d = date_type.fromisoformat(row['date'])
                await self.repo.upsert_aw_app(d, row['app_name'], row.get('source', 'window'), int(row['duration_seconds']))

    async def import_notes(self, zip_file, slug_to_id: dict) -> None:
        if 'notes.csv' not in zip_file.namelist():
            return
        text = zip_file.read('notes.csv').decode('utf-8')
        for row in csv.DictReader(StringIO(text)):
            mid = slug_to_id.get(row.get('metric_slug', ''))
            if not mid:
                continue
            d = date_type.fromisoformat(row['date'])
            note_text = row.get('text', '')
            if note_text and not await self.repo.check_note_exists(mid, d, note_text):
                await self.repo.insert_note(mid, d, note_text)

    @staticmethod
    def _resolve_slot_id(row: dict, metric_id: int, slot_lookup: dict) -> int | None:
        csv_so = row.get('slot_sort_order', '')
        if csv_so in ('', None):
            return None
        try:
            so = int(csv_so)
            if metric_id in slot_lookup and so in slot_lookup[metric_id]:
                return slot_lookup[metric_id][so]
        except (ValueError, TypeError):
            pass
        return None

    async def _coerce_value(self, value, mt: str, metric_id: int):
        if mt == "enum":
            if not isinstance(value, list):
                return None
            label_to_id = await self.repo.get_enum_option_labels(metric_id)
            ids = [label_to_id[lbl] for lbl in value if lbl in label_to_id]
            return ids if ids else None
        if mt == "time":
            return value if isinstance(value, str) else None
        if mt in ("number", "duration", "scale"):
            try:
                return int(value)
            except (ValueError, TypeError):
                return None
        return bool(value.get('value', False)) if isinstance(value, dict) else bool(value)
