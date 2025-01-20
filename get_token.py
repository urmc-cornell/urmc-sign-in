from google_auth_oauthlib.flow import InstalledAppFlow
import pickle
import os

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/forms.responses.readonly',
          'https://www.googleapis.com/auth/forms.body.readonly']

def get_oauth_token():
    creds = None
    
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            'client_secrets.json',  # Your downloaded client secrets file
            SCOPES)
        creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return creds.token

if __name__ == '__main__':
    token = get_oauth_token()
    print("Your OAuth token is:", token)