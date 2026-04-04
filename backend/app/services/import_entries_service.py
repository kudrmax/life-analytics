"""Entry import logic — extracted from ImportService for 300-line rule."""

import csv
import json
from datetime import date as date_type
from io import StringIO

from app.domain.enums import MetricType
from app.repositories.entry_repository import EntryRepository


class EntryImporter:
    """Handles importing entries and auxiliary data (AW, notes) from ZIP."""

    def __init__(self, repo, conn) -> None:
        self.repo = repo
        self.conn = conn
        self.entry_repo = EntryRepository(conn, repo.user_id)

    async def import_entries(
        self, zip_file, slug_to_id: dict, slug_to_type: dict,
    ) -> tuple[int, int, list[str]]:
        imported = 0
        skipped = 0
        errors: list[str] = []

        all_metric_ids = list(slug_to_id.values())
        checkpoint_lookup = await self.repo.get_checkpoint_lookup(all_metric_ids)
        global_label_lookup = await self.repo.get_global_checkpoint_label_lookup()

        text = zip_file.read('entries.csv').decode('utf-8')
        reader = csv.DictReader(StringIO(text))

        for row_num, row in enumerate(reader, start=2):
            try:
                slug = row.get('metric_slug', '')
                metric_id = slug_to_id.get(slug)
                if not metric_id or slug_to_type.get(slug) in (MetricType.computed, MetricType.text):
                    skipped += 1
                    continue

                d = date_type.fromisoformat(row['date'])
                checkpoint_id, interval_id = self._resolve_entry_binding(
                    row, metric_id, checkpoint_lookup, global_label_lookup)

                # Backward compat: old format with slot_sort_order
                if checkpoint_id is None and interval_id is None:
                    csv_so = row.get('slot_sort_order', '')
                    if csv_so not in ('', None):
                        try:
                            so = int(csv_so)
                            label = row.get('slot_label', '') or row.get('checkpoint_label', '') or f'Checkpoint {so}'
                            # Create checkpoint as deleted (not in metric's checkpoint_labels = was deleted)
                            new_cp_id = await self.repo.find_or_create_checkpoint(label, deleted=True)
                            checkpoint_lookup[metric_id][so] = new_cp_id
                            global_label_lookup[label] = new_cp_id
                            checkpoint_id = new_cp_id
                        except (ValueError, TypeError):
                            pass

                # Handle new checkpoint_id from CSV that isn't in lookup
                if checkpoint_id is None and row.get('checkpoint_id', '') not in ('', None):
                    try:
                        raw_cp_id = int(row['checkpoint_id'])
                        label = row.get('checkpoint_label', '') or f'Checkpoint {raw_cp_id}'
                        new_cp_id = await self.repo.find_or_create_checkpoint(label)
                        checkpoint_id = new_cp_id
                    except (ValueError, TypeError):
                        pass

                is_free_cp = row.get('is_free_checkpoint', '') == '1'
                recorded_at_csv = row.get('recorded_at', '') or None

                if await self.repo.check_entry_duplicate(
                    metric_id, d, checkpoint_id, interval_id, is_free_checkpoint=is_free_cp,
                ):
                    skipped += 1
                    continue

                mt = slug_to_type.get(slug, MetricType.bool)
                value = json.loads(row.get('value', 'false'))
                value = await self._coerce_value(value, mt, metric_id)
                if value is None:
                    skipped += 1
                    continue

                async with self.repo.transaction():
                    entry_id = await self.repo.create_entry(
                        metric_id, d, checkpoint_id, interval_id,
                        is_free_checkpoint=is_free_cp,
                        recorded_at=recorded_at_csv,
                    )
                    await self.entry_repo.insert_value(entry_id, value, mt, entry_date=d, metric_id=metric_id)
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
    def _resolve_entry_binding(
        row: dict, metric_id: int, checkpoint_lookup: dict,
        global_label_lookup: dict | None = None,
    ) -> tuple[int | None, int | None]:
        """Resolve checkpoint_id and interval_id from CSV row.

        Returns (checkpoint_id, interval_id) tuple.
        Supports both new format (checkpoint_id/interval_id columns)
        and old format (slot_sort_order column) for backward compatibility.
        """
        # New format: explicit checkpoint_id
        csv_cp = row.get('checkpoint_id', '')
        if csv_cp not in ('', None):
            try:
                return int(csv_cp), None
            except (ValueError, TypeError):
                pass

        # New format: explicit interval_id
        csv_iv = row.get('interval_id', '')
        if csv_iv not in ('', None):
            try:
                return None, int(csv_iv)
            except (ValueError, TypeError):
                pass

        # Old format: slot_sort_order → checkpoint lookup
        csv_so = row.get('slot_sort_order', '')
        if csv_so in ('', None):
            return None, None

        # Try by label first (more reliable — labels are stable across export/import)
        label = row.get('slot_label', '') or row.get('checkpoint_label', '')
        if label and global_label_lookup and label in global_label_lookup:
            return global_label_lookup[label], None

        # Fallback: try by sort_order
        try:
            so = int(csv_so)
            if metric_id in checkpoint_lookup and so in checkpoint_lookup[metric_id]:
                return checkpoint_lookup[metric_id][so], None
        except (ValueError, TypeError):
            pass
        return None, None

    async def _coerce_value(self, value, mt: str, metric_id: int):
        if mt == MetricType.enum:
            if not isinstance(value, list):
                return None
            label_to_id = await self.repo.get_enum_option_labels(metric_id)
            ids = [label_to_id[lbl] for lbl in value if lbl in label_to_id]
            return ids  # [] is valid — means "no options selected"
        if mt == MetricType.time:
            return value if isinstance(value, str) else None
        if mt in (MetricType.number, MetricType.duration, MetricType.scale):
            try:
                return int(value)
            except (ValueError, TypeError):
                return None
        return bool(value.get('value', False)) if isinstance(value, dict) else bool(value)
