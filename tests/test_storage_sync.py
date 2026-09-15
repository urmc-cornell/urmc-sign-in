import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import sync_service as sync


class StorageSyncTests(unittest.TestCase):
    def test_lists_advisors_nested_folders_and_pages(self):
        client = MagicMock()
        def listing(folder, options):
            if folder == '':
                return [{'name': 'advisors', 'id': None, 'metadata': None},
                        {'name': 'eboard', 'id': None, 'metadata': None}]
            if folder == 'advisors':
                return [{'name': 'photo.jpg', 'id': 'advisor', 'metadata': {'size': 10}}]
            if options['offset'] == 0:
                return [{'name': f'{i}.jpg', 'id': str(i), 'metadata': {'size': 1}} for i in range(1000)]
            return [{'name': 'last.jpg', 'id': 'last', 'metadata': {'size': 2}}]
        client.storage.from_.return_value.list.side_effect = listing
        files = sync._list_headshots(client)
        self.assertEqual(len(files), 1002)
        self.assertIn('advisors/photo.jpg', [f['name'] for f in files])
        self.assertIn('eboard/last.jpg', [f['name'] for f in files])

    def test_upload_retries_without_deleting_existing_photo(self):
        source, destination = MagicMock(), MagicMock()
        source.storage.from_.return_value.download.return_value = b'photo'
        bucket = destination.storage.from_.return_value
        bucket.upload.side_effect = [BlockingIOError(35, 'Resource temporarily unavailable'), None]
        results = {'errors': [], 'headshots': 0}
        with patch.object(sync, 'get_client', side_effect=[source, destination]), patch.object(sync.time, 'sleep'):
            sync._transfer_headshots('staging', 'production', [{'name': 'advisors/photo.jpg'}], results)
        self.assertEqual(results, {'errors': [], 'headshots': 1})
        self.assertEqual(bucket.upload.call_count, 2)
        self.assertEqual(bucket.upload.call_args.args[2]['upsert'], 'true')
        bucket.remove.assert_not_called()

    def test_permanent_upload_failure_preserves_old_object(self):
        source, destination = MagicMock(), MagicMock()
        destination.storage.from_.return_value.upload.side_effect = OSError('unavailable')
        results = {'errors': [], 'headshots': 0}
        with patch.object(sync, 'get_client', side_effect=[source, destination]), patch.object(sync.time, 'sleep'):
            sync._transfer_headshots('staging', 'production', [{'name': 'eboard/ruth.jpg'}], results)
        self.assertEqual(results['headshots'], 0)
        self.assertIn('eboard/ruth.jpg', results['errors'][0])
        destination.storage.from_.return_value.remove.assert_not_called()

    def test_source_listing_failure_stops_before_database_mutation(self):
        for operation in [sync.push_to_production, sync.pull_from_production]:
            with self.subTest(operation=operation.__name__), patch.object(sync, 'get_client', return_value=MagicMock()), patch.object(sync, '_list_headshots', side_effect=OSError('list failed')), patch.object(sync, '_delete_all_rows') as delete:
                result = operation()
                self.assertTrue(result['errors'])
                delete.assert_not_called()

    def test_cleanup_preserves_full_folder_paths(self):
        client = MagicMock()
        count = sync._delete_extra_headshots(client, [{'name': 'eboard/keep.jpg'}],
            [{'name': 'eboard/keep.jpg'}, {'name': 'advisors/old.jpg'}])
        self.assertEqual(count, 1)
        client.storage.from_.return_value.remove.assert_called_once_with(['advisors/old.jpg'])
