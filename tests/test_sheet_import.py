import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'web')]
import sheet_import as importer


class SheetImportTests(unittest.TestCase):
    def source(self):
        return {'headers':['Email','Name','Major','Bio','Photo'],
                'columns':importer.PROFILE_FIELDS, 'env':'staging',
                'rows':[['AA123@cornell.edu','Avery Adams','CS','','https://drive.google.com/open?id=photo1'],
                        ['bb234@cornell.edu','Blair Baker','IS','  ','https://drive.google.com/open?id=photo2']]}

    def test_email_mapping_preserves_blank_and_unmapped_fields(self):
        rows = importer.mapped_rows(self.source(), ['netid','full_name','major','bio',''])
        self.assertEqual(rows[0]['netid'],'aa123')
        self.assertEqual(rows[0]['values'],{'first_name':'Avery','last_name':'Adams','major':'CS'})
        self.assertNotIn('bio',rows[1]['values'])
        self.assertNotIn('role',rows[0]['values'])

    def test_invalid_email_row_is_visible_and_disabled(self):
        source = self.source(); source['rows'][0][0] = 'person@gmail.com'
        rows = importer.mapped_rows(source,['netid','full_name','','',''])
        self.assertIn('cornell.edu',rows[0]['error'])

    def test_duplicate_destinations_and_missing_identity_rejected(self):
        for mapping in [['','full_name','','',''], ['netid','major','major','','']]:
            with self.assertRaises(ValueError): importer.mapped_rows(self.source(),mapping)

    def test_only_selected_people_and_mapped_fields_are_updated(self):
        source = self.source()
        source['mapped_rows'] = importer.mapped_rows(source,['netid','','major','',''])
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{'id':7}]
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{'id':7}]
        with patch.object(importer,'get_client',return_value=sb), patch.object(importer,'download_and_upload_headshot') as photo:
            result = importer.apply_rows(source,[1],object())
        self.assertTrue(result[0]['ok'])
        sb.table.return_value.update.assert_called_once_with({'major':'IS'})
        sb.table.return_value.update.return_value.eq.assert_called_once_with('id',7)
        sb.table.return_value.select.return_value.eq.assert_called_once_with('netid','bb234')
        photo.assert_not_called()

    def test_only_selected_headshot_is_uploaded(self):
        source = self.source(); source['mapped_rows'] = importer.mapped_rows(source,['netid','','','','headshot_url'])
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{'id':1}]
        with patch.object(importer,'get_client',return_value=sb), patch.object(importer,'download_and_upload_headshot',return_value='https://example.com/photo') as photo:
            importer.apply_rows(source,[0],object())
        self.assertEqual(photo.call_count,1)
        self.assertEqual(photo.call_args.args[:3],('photo1','aa123','Primary'))
        sb.table.return_value.update.assert_called_once_with({'headshot_url':'https://example.com/photo'})

    def test_duplicate_person_selection_rejected(self):
        source = self.source(); source['rows'][1][0] = 'aa123@cornell.edu'
        source['mapped_rows'] = importer.mapped_rows(source,['netid','','major','',''])
        with self.assertRaises(ValueError): importer.apply_rows(source,[0,1],object())

    def test_new_member_needs_name(self):
        source = self.source(); source['mapped_rows'] = importer.mapped_rows(source,['netid','','major','',''])
        sb = MagicMock(); sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        with patch.object(importer,'get_client',return_value=sb): result = importer.apply_rows(source,[0],object())
        self.assertFalse(result[0]['ok']); sb.table.return_value.insert.assert_not_called()

    def test_failed_photo_does_not_save_other_fields(self):
        source = self.source(); source['mapped_rows'] = importer.mapped_rows(source,['netid','','major','','headshot_url'])
        sb = MagicMock(); sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{'id':1}]
        with patch.object(importer,'get_client',return_value=sb), patch.object(importer,'download_and_upload_headshot',return_value=None):
            result = importer.apply_rows(source,[0],object())
        self.assertFalse(result[0]['ok']); sb.table.return_value.update.assert_not_called()

    def test_sheet_tab_headers_and_real_database_columns(self):
        http = MagicMock(); http.get.side_effect = [
            SimpleNamespace(ok=True,json=lambda:{'sheets':[{'properties':{'title':"Member's Responses"}}]}),
            SimpleNamespace(ok=True,json=lambda:{'values':[['Email','Major'],['aa123@cornell.edu','CS']]})]
        sb = MagicMock(); sb.table.return_value.select.return_value.limit.return_value.execute.return_value.data = [{'id':1,'netid':'aa123','major':'CS'}]
        with patch.object(importer,'AuthorizedSession') as session, patch.object(importer,'get_client',return_value=sb):
            session.return_value.__enter__.return_value = http
            source = importer.read_sheet('abc123',None,object(),'staging')
        self.assertEqual(source['columns'],['major'])
        self.assertIn('%27%27',http.get.call_args.args[0])
        self.assertNotIn('A:Z',http.get.call_args.args[0])

    def test_route_binds_loaded_sheet_to_session_and_environment(self):
        from app import app, loaded_sheets
        app.secret_key = 'test-only-secret'
        http = app.test_client()
        self.assertEqual(http.post('/member_sheet/load',json={}).status_code,401)
        with http.session_transaction() as session:
            session['credentials'] = True
        fixture = {**self.source(),'sheet_id':'abc123','tab':'Responses','tabs':['Responses']}
        with patch('app.get_credentials',return_value=object()), patch('app.save_credentials'), patch('app.read_sheet',return_value=fixture):
            response = http.post('/member_sheet/load',json={'sheet_id':'abc123'})
        token = response.get_json()['token']
        self.assertEqual(http.post('/member_sheet/map',json={'token':'wrong','mapping':[]}).status_code,400)
        with http.session_transaction() as session: session['env'] = 'production'
        self.assertEqual(http.post('/member_sheet/apply',json={'token':token,'selected':[0]}).status_code,400)
        loaded_sheets.clear()

    def test_expired_google_login_has_actionable_error(self):
        with patch.object(importer,'AuthorizedSession') as session:
            session.return_value.__enter__.return_value.get.side_effect = RefreshError('Missing refresh token')
            with self.assertRaisesRegex(ValueError,'Log out.*sign in again'):
                importer.read_sheet('abc123',None,object(),'staging')

    def test_login_requests_refresh_token_on_repeat_signin(self):
        from app import app
        app.secret_key = 'test-only-secret'
        flow = MagicMock()
        flow.authorization_url.return_value = ('https://accounts.google.com/example','state')
        flow.code_verifier = None
        with patch('app.Flow.from_client_secrets_file',return_value=flow):
            response = app.test_client().get('/login')
        self.assertEqual(response.status_code,302)
        self.assertEqual(flow.authorization_url.call_args.kwargs['access_type'],'offline')
        self.assertIn('consent',flow.authorization_url.call_args.kwargs['prompt'].split())

    def test_credentials_retain_expiry_and_refresh_fields(self):
        from app import app, get_credentials, save_credentials
        credentials = Credentials(token='test-access',refresh_token='test-refresh',
            token_uri='https://oauth2.googleapis.com/token',client_id='test-client',
            client_secret='test-secret',scopes=['test-scope'],expiry=datetime(2020,1,1))
        with app.test_request_context():
            save_credentials(credentials)
            restored = get_credentials()
            self.assertTrue(restored.expired)
            self.assertEqual(restored.refresh_token,'test-refresh')
            restored.token = 'refreshed-access'
            save_credentials(restored)
            self.assertEqual(get_credentials().token,'refreshed-access')


if __name__ == '__main__': unittest.main()
