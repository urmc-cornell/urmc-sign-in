"""Google Sheet -> mapped member fields -> selected rows. No writes during loading."""
import re
from urllib.parse import quote
from google.auth.transport.requests import AuthorizedSession
from google.auth.exceptions import RefreshError, TransportError
from requests.exceptions import RequestException
from supabase_clients import get_client
from point_service import download_and_upload_headshot, _extract_drive_file_id

# These are existing profile columns, not a new schema. Only columns actually
# present in the members table are offered; IDs and points aren't editable here.
PROFILE_FIELDS = ['first_name', 'last_name', 'major', 'graduation_year', 'position',
                  'bio', 'ask_about', 'linkedin_url', 'instagram_url', 'role',
                  'headshot_url', 'secondary_headshot_url']


def read_sheet(sheet_id, tab, credentials, env):
    if not re.fullmatch(r'[\w-]+', sheet_id):
        raise ValueError('Invalid Google Sheet ID.')
    if credentials is None:
        raise ValueError('Your Google login is missing. Log out and sign in again.')
    try:
        with AuthorizedSession(credentials) as http:
            base = f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}'

            def get(url, **kwargs):
                response = http.get(url, timeout=45, **kwargs)
                if not response.ok:
                    try:
                        detail = response.json().get('error', {}).get('message', '')
                    except (ValueError, AttributeError):
                        detail = ''
                    raise ValueError(f'Google Sheets returned {response.status_code}: '
                                     + (detail or 'Check that your signed-in account can open this sheet.'))
                return response.json()

            metadata = get(base, params={'fields': 'sheets.properties'})
            tabs = [s['properties']['title'] for s in metadata.get('sheets', [])]
            tab = tab or (tabs[0] if tabs else None)
            if tab not in tabs:
                raise ValueError('Choose a valid sheet tab.')
            sheet_range = "'" + tab.replace("'", "''") + "'"
            rows = get(base + '/values/' + quote(sheet_range, safe='')).get('values', [])
    except RefreshError as error:
        raise ValueError('Your Google login expired and could not be refreshed. '
                         'Log out of the dashboard, sign in again, then reload the sheet.') from error
    except (TransportError, RequestException) as error:
        raise ValueError(f'Could not connect to Google Sheets ({type(error).__name__}). '
                         'Check the network connection; the terminal has the technical details.') from error
    if len(rows) < 2:
        raise ValueError('This tab needs a header row and at least one response.')
    try:
        sample = get_client(env).table('members').select('*').limit(1).execute().data or []
    except Exception as error:
        raise ValueError(f'The sheet loaded, but the {env} Supabase members table could not be read '
                         f'({type(error).__name__}). Check that environment’s connection/settings.') from error
    if not sample:
        raise ValueError('The members table is empty; cannot confirm its columns.')
    columns = [field for field in PROFILE_FIELDS if field in sample[0]]
    return {'sheet_id': sheet_id, 'tab': tab, 'tabs': tabs, 'headers': rows[0],
            'rows': rows[1:], 'columns': columns, 'env': env}


def identity(value):
    value = value.strip().lower()
    if '@' in value:
        local, domain = value.rsplit('@', 1)
        if domain != 'cornell.edu':
            raise ValueError('Email must end in @cornell.edu.')
        value = local
    if not re.fullmatch(r'[a-z][a-z0-9]{1,19}', value):
        raise ValueError('Missing or invalid NetID/email.')
    return value


def mapped_rows(source, mapping):
    if not isinstance(mapping, list) or len(mapping) != len(source['headers']):
        raise ValueError('Map the sheet headers first.')
    targets = [field for field in mapping if field]
    allowed = source['columns'] + ['netid', 'full_name']
    if any(field not in allowed for field in targets) or len(set(targets)) != len(targets):
        raise ValueError('Each destination column can be mapped only once.')
    if targets.count('netid') != 1:
        raise ValueError('Map one email or NetID column to netid.')
    if 'full_name' in targets and ('first_name' in targets or 'last_name' in targets):
        raise ValueError('Choose Full name OR separate first_name/last_name mappings.')
    if 'full_name' in targets and not {'first_name', 'last_name'}.issubset(source['columns']):
        raise ValueError('Full name requires first_name and last_name database columns.')
    if len(targets) < 2:
        raise ValueError('Map at least one field to update, in addition to netid.')
    rows = []
    for index, cells in enumerate(source['rows']):
        if not any(str(cell).strip() for cell in cells):
            continue
        row = {'index': index, 'sheet_row': index + 2, 'netid': '', 'values': {}, 'error': ''}
        try:
            for column, field in enumerate(mapping):
                value = str(cells[column]).strip() if column < len(cells) else ''
                if field == 'netid':
                    row['netid'] = identity(value)
                elif not field or not value:
                    continue  # Missing/blank answers never erase current values.
                elif field == 'full_name':
                    parts = value.split(maxsplit=1)
                    row['values']['first_name'] = parts[0]
                    if len(parts) > 1:
                        row['values']['last_name'] = parts[1]
                elif field in ('ask_about', 'role'):
                    row['values'][field] = [part.strip() for part in value.split(',') if part.strip()]
                else:
                    row['values'][field] = value
            if not row['values']:
                raise ValueError('No nonblank mapped fields to update.')
        except ValueError as error:
            row['error'] = str(error)
        rows.append(row)
    return rows


def apply_rows(source, selected, credentials):
    if not isinstance(selected, list) or not selected or any(type(i) is not int for i in selected):
        raise ValueError('Select at least one person.')
    available = {row['index']: row for row in source['mapped_rows']}
    if len(set(selected)) != len(selected) or any(i not in available or available[i]['error'] for i in selected):
        raise ValueError('Invalid row selection. Load the people again.')
    chosen = [available[i] for i in selected]
    if len({row['netid'] for row in chosen}) != len(chosen):
        raise ValueError('Select only one response per NetID.')
    results = []
    completed = source.setdefault('completed', set())
    for row in chosen:
        if row['netid'] in completed:
            results.append({'index': row['index'], 'netid': row['netid'], 'ok': True})
            continue
        try:
            sb = get_client(source['env'])
            found = sb.table('members').select('id').eq('netid', row['netid']).execute().data or []
            if len(found) > 1:
                raise ValueError('More than one database member has this NetID.')
            values = dict(row['values'])
            if not found and not values.get('first_name'):
                raise ValueError('New member: map a name column before adding this person.')
            for field, kind in [('headshot_url', 'Primary'), ('secondary_headshot_url', 'Secondary')]:
                if field not in values:
                    continue
                file_id = _extract_drive_file_id(values[field])
                if not file_id or not re.fullmatch(r'[\w-]+', file_id):
                    raise ValueError(f'{field}: use a Google Drive file link.')
                url = download_and_upload_headshot(file_id, row['netid'], kind,
                    credentials, row['netid'], env=source['env'])
                if not url:
                    raise ValueError(f'{field}: could not upload the headshot.')
                values[field] = url
            # Reacquire after the existing headshot helper creates its own client.
            sb = get_client(source['env'])
            if found:
                response = sb.table('members').update(values).eq('id', found[0]['id']).execute()
            else:
                response = sb.table('members').insert({'netid': row['netid'], **values}).execute()
            if not response.data:
                raise ValueError('No member was saved.')
            completed.add(row['netid'])
            results.append({'index': row['index'], 'netid': row['netid'], 'ok': True})
        except Exception as error:
            results.append({'index': row['index'], 'netid': row['netid'], 'ok': False, 'error': str(error)})
    return results
