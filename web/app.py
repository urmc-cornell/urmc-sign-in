from flask import Flask, session, redirect, request, send_file, jsonify
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import os
import re
from pathlib import Path
import sys

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Allows HTTP (instead of HTTPS) for local development

# Add backend directory to path so we can import point_service
backend_dir = Path(__file__).parent.parent / 'backend'
sys.path.append(str(backend_dir))

from point_service import add_or_update_points, retrieve_event_responses, retrieve_eboard_responses, retrieve_eboard_from_sheet, retrieve_ta_responses, add_event
from sync_service import push_to_production, pull_from_production

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

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
        'client_secrets.json',
        scopes=SCOPES,
        redirect_uri='http://localhost:8080/oauth2callback'
    )
    # Generate the authorization URL and save the state
    authorization_url, state = flow.authorization_url(access_type='offline')
    session['state'] = state
    # Redirect the user to the Google login page
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    # Initialize the OAuth2 flow
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=SCOPES,
        state=session['state']
    )
    flow.redirect_uri = 'http://localhost:8080/oauth2callback'
    
    # Fetch the token from the authorization response
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    # Save the credentials in the session
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
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

    # Retrieve credentials from session
    credentials_info = session.get('credentials')
    credentials = Credentials(
        token=credentials_info['token'],
        refresh_token=credentials_info['refresh_token'],
        token_uri=credentials_info['token_uri'],
        client_id=credentials_info['client_id'],
        client_secret=credentials_info['client_secret'],
        scopes=credentials_info['scopes']
    )
    
    env = session.get('env', 'staging')
    try:
        # If credentials are not provided, raise an error
        if not credentials:
            raise ValueError("Credentials are required")
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

    credentials_info = session.get('credentials')
    credentials = Credentials(
        token=credentials_info['token'],
        refresh_token=credentials_info['refresh_token'],
        token_uri=credentials_info['token_uri'],
        client_id=credentials_info['client_id'],
        client_secret=credentials_info['client_secret'],
        scopes=credentials_info['scopes']
    )

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
    
    credentials_info = session.get('credentials')
    credentials = Credentials(
        token=credentials_info['token'],
        refresh_token=credentials_info['refresh_token'],
        token_uri=credentials_info['token_uri'],
        client_id=credentials_info['client_id'],
        client_secret=credentials_info['client_secret'],
        scopes=credentials_info['scopes']
    )
    name = request.form['name']
    description = request.form['description']
    flyer_url = request.form['flyer_url']
    insta = request.form.get('insta', None)
    month = request.form['month']
    day = request.form['day']
    year = request.form['year']
    env = session.get('env', 'staging')
    try:
        # If credentials are not provided, raise an error
        if not credentials:
            raise ValueError("Credentials are required")

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
        session['message'] = f"Push complete! Members: {results['members']}, Events: {results['events']}, Points: {results['points']}, Headshots: {results['headshots']}.{error_text}"
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
        session['message'] = f"Pull complete! Members: {results['members']}, Events: {results['events']}, Points: {results['points']}, Headshots: {results['headshots']}.{error_text}"
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