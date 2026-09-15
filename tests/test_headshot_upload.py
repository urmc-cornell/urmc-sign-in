import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import point_service
import sheet_import


class HeadshotUploadTests(unittest.TestCase):
    def setUp(self):
        self.sb = MagicMock()
        self.bucket = self.sb.storage.from_.return_value
        self.credentials = SimpleNamespace(token='test-token')
        response = SimpleNamespace(status_code=200, content=b'source-image')
        for name, kwargs in [
            ('requests.get', {'return_value': response}),
            ('crop_image_to_square', {'return_value': b'jpeg-image'}),
            ('get_client', {'return_value': self.sb}),
            ('get_supabase_url', {'return_value': 'https://test.supabase.co'}),
        ]:
            patcher = patch('point_service.' + name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def upload(self):
        return point_service.download_and_upload_headshot(
            'drive-file', 'AA123', 'Primary', self.credentials, env='staging')

    def test_replacements_upload_distinct_objects_and_return_storage_urls(self):
        urls = [self.upload(), self.upload()]
        paths = [call.args[0] for call in self.bucket.upload.call_args_list]
        self.assertNotEqual(paths[0], paths[1])
        for path, url in zip(paths, urls):
            self.assertRegex(path, r'^eboard/aa123Primary-[0-9a-f]{32}\.jpeg$')
            self.assertEqual(url, 'https://test.supabase.co/storage/v1/object/public/headshots/' + path)
        self.bucket.remove.assert_not_called()

    def test_upload_failure_never_deletes_existing_photo(self):
        for error in ['already exists', 'network unavailable']:
            with self.subTest(error=error):
                self.bucket.upload.side_effect = Exception(error)
                self.assertIsNone(self.upload())
                self.bucket.remove.assert_not_called()

    def test_database_failure_keeps_existing_storage_object(self):
        self.sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{'id': 1}]
        self.sb.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception('write failed')
        source = {'env': 'staging', 'mapped_rows': [
            {'index': 0, 'netid': 'aa123', 'error': '',
             'values': {'headshot_url': 'https://drive.google.com/open?id=photo1'}}
        ]}
        with patch.object(sheet_import, 'get_client', return_value=self.sb):
            results = sheet_import.apply_rows(source, [0], self.credentials)
        self.assertFalse(results[0]['ok'])
        self.bucket.upload.assert_called_once()
        self.bucket.remove.assert_not_called()
        saved_url = self.sb.table.return_value.update.call_args.args[0]['headshot_url']
        self.assertTrue(saved_url.startswith('https://test.supabase.co/storage/'))
        self.assertEqual(source['completed'], set())


if __name__ == '__main__':
    unittest.main()
