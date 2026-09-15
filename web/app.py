from flask import Flask, session, redirect, request, send_file, jsonify
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv
import os
import re
import secrets
import time
from datetime import datetime
from threading import RLock
from pathlib import Path
import sys

load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Allows HTTP (instead of HTTPS) for local development

# Add backend directory to path so we can import point_service
backend_dir = Path(__file__).parent.parent / 'backend'
sys.path.append(str(backend_dir))

from point_service import add_or_update_points, retrieve_event_responses, retrieve_eboard_responses, retrieve_eboard_from_sheet, retrieve_ta_responses, add_event
from sync_service import push_to_production, pull_from_production
from sheet_import import read_sheet, mapped_rows, apply_rows

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

# One temporary loaded sheet per browser session; no new database or draft system.
loaded_sheets = {}
sheet_lock = RLock()


@app.route('/member_sheet/<action>', methods=['POST'])
def member_sheet(action):
    if 'credentials' not in session:
        return jsonify(error='Please log in again.'), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Expected a JSON request.'), 400
    try:
        with sheet_lock:
            for key in list(loaded_sheets):
                if loaded_sheets[key]['expires'] < time.time():
                    del loaded_sheets[key]
            if action == 'load':
                credentials = get_credentials()
                source = read_sheet(extract_sheet_id(data.get('sheet_id', '')),
                                    data.get('tab'), credentials, session.get('env', 'staging'))
                save_credentials(credentials)
                old_token = session.get('member_sheet_token')
                loaded_sheets.pop(old_token, None)
                token = secrets.token_urlsafe(24)
                session['member_sheet_token'] = token
                source['expires'] = time.time() + 3600
                loaded_sheets[token] = source
                return jsonify(token=token, **{key: source[key] for key in ('tab', 'tabs', 'headers', 'columns', 'env')})
            token = data.get('token')
            if not token or token != session.get('member_sheet_token') or token not in loaded_sheets:
                raise ValueError('The loaded sheet expired. Load it again.')
            source = loaded_sheets[token]
            if source['env'] != session.get('env', 'staging'):
                raise ValueError('Environment changed. Load the sheet again before updating.')
            if action == 'map':
                source['mapped_rows'] = mapped_rows(source, data.get('mapping'))
                source['completed'] = set()
                return jsonify(rows=source['mapped_rows'], env=source['env'])
            if action == 'apply':
                if 'mapped_rows' not in source:
                    raise ValueError('Map the columns and show people first.')
                results = apply_rows(source, data.get('selected'), get_credentials())
                return jsonify(results=results)
            raise ValueError('Unknown sheet action.')
    except ValueError as error:
        app.logger.warning('Member sheet import: %s', error, exc_info=error.__cause__ is not None)
        return jsonify(error=str(error)), 400
    except Exception as error:
        app.logger.exception('Member sheet import failed')
        return jsonify(error=f'Could not process the sheet ({type(error).__name__}). '
                       'The terminal running the dashboard contains the traceback.'), 502

def extract_form_id(input_str):
    """Extract Google Form ID from a URL or return the raw ID."""
    input_str = input_str.strip()
    if 'docs.google.com/forms' in input_str:
        # /d/e/ is the published link — has a different encoded ID that won't work with the API
        if '/d/e/' in input_str:
            raise ValueError("This is a published form link. Please use the edit link from your browser bar (the URL when you have the form open in edit mode).")
        # Match /d/{ID} (the actual form ID)
        match = re.search(r'/forms/d/([a-zA-Z0-9_-]+)', input_str)
        if match:
            return match.group(1)
        raise ValueError("Could not extract form ID from this URL. Please paste the edit link or just the form ID.")
    return input_str

def extract_sheet_id(input_str):
    """Extract Google Sheet ID from a URL or return the raw ID."""
    input_str = input_str.strip()
    if 'docs.google.com/spreadsheets' in input_str:
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', input_str)
        if match:
            return match.group(1)
        raise ValueError("Could not extract sheet ID from this URL. Please paste the sheet link or just the sheet ID.")
    return input_str

SCOPES = [
    'https://www.googleapis.com/auth/forms.responses.readonly',
    'https://www.googleapis.com/auth/forms.body.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]

def get_credentials():
    """Reconstruct Google credentials from session. Returns None if session is missing/invalid."""
    credentials_info = session.get('credentials')
    if not credentials_info:
        return None
    return Credentials(
        token=credentials_info['token'],
        refresh_token=credentials_info['refresh_token'],
        token_uri=credentials_info['token_uri'],
        client_id=credentials_info['client_id'],
        client_secret=credentials_info['client_secret'],
        scopes=credentials_info['scopes'],
        expiry=datetime.fromisoformat(credentials_info['expiry']) if credentials_info.get('expiry') else None
    )


def save_credentials(credentials):
    # Keep refreshed access tokens and their expiry rather than reusing an expired token.
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes,
        'expiry': credentials.expiry.isoformat() if credentials.expiry else None
    }

@app.route('/')
def index():
    # If user is not logged in, redirect to login page
    if 'credentials' not in session:
        return redirect('/login')
    # If user is logged in, serve the dashboard
    return send_file('dashboard.html')

@app.route('/login')
def login():
    # Initialize the OAuth2 flow
    flow = Flow.from_client_secrets_file(
        str(Path(__file__).parent.parent / 'client_secrets.json'),
        scopes=SCOPES,
        redirect_uri='http://localhost:8080/oauth2callback'
    )
    # Generate the authorization URL and save the state
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        # Offline access alone may omit the refresh token on repeat sign-ins.
        prompt='select_account consent'
    )
    session['state'] = state
    # Save the PKCE code_verifier if the library auto-generated one
    if getattr(flow, 'code_verifier', None):
        session['code_verifier'] = flow.code_verifier
    # Redirect the user to the Google login page
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    # Initialize the OAuth2 flow
    flow = Flow.from_client_secrets_file(
        str(Path(__file__).parent.parent / 'client_secrets.json'),
        scopes=SCOPES,
        state=session['state']
    )
    flow.redirect_uri = 'http://localhost:8080/oauth2callback'
    # Restore the PKCE code_verifier from the session
    flow.code_verifier = session.pop('code_verifier', None)

    # Fetch the token from the authorization response
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    # Save the credentials in the session
    save_credentials(credentials)
    # Redirect the user to the dashboard
    return redirect('/')

@app.route('/update_points', methods=['POST'])
def update_points():
    # If user is not logged in, redirect to login page
    if 'credentials' not in session:
        return redirect('/login')
    
    # Get the netid, points, and reason from the request
    netid = request.form['netid']
    points = int(request.form['points'])
    reason = request.form['reason']
    
    env = session.get('env', 'staging')
    try:
        add_or_update_points(netid=netid, points_to_add=points, reason=reason, env=env)
        session['message'] = "Points updated successfully!"
    except Exception as e:
        session['message'] = f"Error: {str(e)}"
    return redirect('/')

@app.route('/process_form/<form_type>', methods=['POST'])
def process_form(form_type):
    # If user is not logged in, redirect to login page 
    if 'credentials' not in session:
        return redirect('/login')
    # Get the form id and points value from the request
    
    try:
        form_id = extract_form_id(request.form['form_id'])
        print(f"Form ID: {form_id}")
    except ValueError as e:
        session['message'] = f"Error: {str(e)}"
        return redirect('/')

    if form_type != 'eboard' and form_type != 'ta':
        points_value = int(request.form['points_value'])
    else:
        points_value = 0

    credentials = get_credentials()
    if not credentials:
        return redirect('/login')

    env = session.get('env', 'staging')
    try:
        # Retrieve and process the form responses
        if form_type == 'eboard':
            retrieve_eboard_responses(form_id, credentials, env=env)
        elif form_type == 'ta':
            retrieve_ta_responses(form_id, credentials, env=env)
        else:
            retrieve_event_responses(form_id, points_value, credentials, env=env)
        session['message'] = "Form responses processed successfully!"
    except Exception as e:
        session['message'] = f"Error: {str(e)}"
    return redirect('/')
    
@app.route('/process_sheet/eboard', methods=['POST'])
def process_sheet_eboard():
    if 'credentials' not in session:
        return redirect('/login')
    try:
        sheet_id = extract_sheet_id(request.form['sheet_id'])
    except ValueError as e:
        session['message'] = f"Error: {str(e)}"
        return redirect('/')

    credentials = get_credentials()
    if not credentials:
        return redirect('/login')

    env = session.get('env', 'staging')
    try:
        retrieve_eboard_from_sheet(sheet_id, credentials, env=env)
        session['message'] = "Sheet responses processed successfully!"
    except Exception as e:
        session['message'] = f"Error: {str(e)}"
    return redirect('/')

@app.route('/add_event', methods=['POST'])
def process_event():
    if 'credentials' not in session:
        return redirect('/login')
    
    credentials = get_credentials()
    if not credentials:
        return redirect('/login')

    name = request.form['name']
    description = request.form['description']
    flyer_url = request.form['flyer_url']
    insta = request.form.get('insta', None)
    month = request.form['month']
    day = request.form['day']
    year = request.form['year']
    env = session.get('env', 'staging')
    try:
        add_event(name, description, flyer_url, insta, month, day, year, env=env)
        session['message'] = "Event added successfully!"
    except Exception as e:
        session['message'] = f"Error: {str(e)}"
    return redirect('/')

@app.route('/set_env', methods=['POST'])
def set_env():
    env = request.form.get('env', 'staging')
    if env not in ('staging', 'production'):
        env = 'staging'
    session['env'] = env
    return redirect('/')

@app.route('/get_env')
def get_env():
    return jsonify({'env': session.get('env', 'staging')})

@app.route('/get_message')
def get_message():
    msg = session.pop('message', None)
    return jsonify({'message': msg})

@app.route('/push_to_production', methods=['POST'])
def push_to_prod():
    if 'credentials' not in session:
        return redirect('/login')
    try:
        results = push_to_production()
        error_text = f" Errors: {results['errors']}" if results['errors'] else ""
        skipped = results.get('skipped_headshots', 0)
        deleted = results.get('deleted_headshots', 0)
        status = "Push finished with errors." if results['errors'] else "Push complete!"
        session['message'] = f"{status} Members: {results['members']}, Events: {results['events']}, Points: {results['points']}, Headshots: {results['headshots']} synced, {skipped} unchanged, {deleted} removed.{error_text}"
    except Exception as e:
        session['message'] = f"Error: {str(e)}"
    return redirect('/')

@app.route('/pull_from_production', methods=['POST'])
def pull_from_prod():
    if 'credentials' not in session:
        return redirect('/login')
    try:
        results = pull_from_production()
        error_text = f" Errors: {results['errors']}" if results['errors'] else ""
        skipped = results.get('skipped_headshots', 0)
        deleted = results.get('deleted_headshots', 0)
        status = "Pull finished with errors." if results['errors'] else "Pull complete!"
        session['message'] = f"{status} Members: {results['members']}, Events: {results['events']}, Points: {results['points']}, Headshots: {results['headshots']} synced, {skipped} unchanged, {deleted} removed.{error_text}"
    except Exception as e:
        session['message'] = f"Error: {str(e)}"
    return redirect('/')

@app.route('/logout')
def logout():
    # Clear the session
    session.clear()
    # Redirect to home page (which will then redirect to login)
    return redirect('/')

if __name__ == '__main__':
    # Run the app on localhost:8080
    app.run('localhost',8080,debug=True)
