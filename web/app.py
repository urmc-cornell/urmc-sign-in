from flask import Flask, session, redirect, request, send_file
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import os
from pathlib import Path
import sys
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv() 

supabase: Client = create_client(
    supabase_url=os.environ.get("SUPABASE_URL"),
    supabase_key=os.environ.get("SUPABASE_KEY")
)

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Allows HTTP (instead of HTTPS) for local development

# Add backend directory to path so we can import point_service
backend_dir = Path(__file__).parent.parent / 'backend'
sys.path.append(str(backend_dir))

from point_service import add_or_update_points, retrieve_event_responses, retrieve_eboard_responses, retrieve_ta_responses, add_event

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

SCOPES = [
    'https://www.googleapis.com/auth/forms.responses.readonly',
    'https://www.googleapis.com/auth/forms.body.readonly'
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
    
    try:
        # Add or update the points
        add_or_update_points(netid=netid, points_to_add=points, reason=reason)
        return "Points updated successfully!"
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/process_form/<form_type>', methods=['POST'])
def process_form(form_type):
    # If user is not logged in, redirect to login page 
    if 'credentials' not in session:
        return redirect('/login')
    # Get the form id and points value from the request
    
    form_id = request.form['form_id']
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
    
    try:
        # If credentials are not provided, raise an error
        if not credentials:
            raise ValueError("Credentials are required")
        # Retrieve and process the form responses
        if form_type == 'eboard':
            retrieve_eboard_responses(form_id, credentials)
        elif form_type == 'ta':
            retrieve_ta_responses(form_id, credentials)
        else:
            retrieve_event_responses(form_id, points_value, credentials)
        return "Form responses processed successfully!"
    except Exception as e:
        return f"Error: {str(e)}", 500
    
@app.route('/add_event', methods=['POST'])
def process_event():
    if 'credentials' not in session:
        return redirect('/login')
    
    try:
        # Get uploaded file
        flyer_file = request.files['flyer_file']
        if not flyer_file or flyer_file.filename == '':
            raise ValueError("No valid file uploaded")

        # Generate unique filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_extension = os.path.splitext(flyer_file.filename)[1]
        unique_filename = f"event-flyers/{timestamp}{file_extension}"
    
        # Upload to Supabase Storage
        upload_response = supabase.storage.from_('event-flyers').upload(
            flyer_file.filename,
            flyer_file.read()
        )
        
        # Get public URL
        flyer_url = supabase.storage.from_('event-flyers').get_public_url(flyer_file.filename)

        # Process other form data
        name = request.form['name']
        description = request.form['description']
        insta = request.form.get('insta', None)
        month = request.form['month']
        day = request.form['day']
        year = request.form['year']
        

        # Insert into events table
        add_event(
            name=name,
            description=description,
            flyer_url=flyer_url,
            insta=insta,
            month=month,
            day=day,
            year=year
        )
        
        return "Event added successfully with image upload!"
    
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/logout')
def logout():
    # Clear the session
    session.clear()
    # Redirect to home page (which will then redirect to login)
    return redirect('/')

if __name__ == '__main__':
    # Run the app on localhost:8080
    app.run('localhost',8080,debug=True)