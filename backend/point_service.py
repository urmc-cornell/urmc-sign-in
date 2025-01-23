from supabase import create_client
import os
import json
import requests
from dotenv import load_dotenv
import pickle
import os.path

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

semester = "sp25"


def main():
    # add_or_update_points("Temi Adebowale", "bbwij34", 2)
    retrieve_event_responses("1SHeCzKB0kczyjTD26fzQabYWYf6U50QVqtan_MA408Q", 3)

def get_oauth_token():
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
            if creds and creds.valid:
                return creds.token
    raise Exception("No valid token found. Please run generate_token.py first")

def add_or_update_points(name: str, netid: str, points_to_add: int):
    try:
        # First check if member exists
        response = supabase.table('members').select('id').eq('netid', netid.lower()).execute()

        if not response.data:
            # Member doesn't exist, create new member
            member_data = {
                'netid': netid.lower(),
                'first_name': name.split()[0],
                'last_name': name.split()[-1] if len(name.split()) > 1 else '',
            }
            member_response = supabase.table('members').insert(member_data).execute()
            member_id = member_response.data[0]['id']
        else:
            member_id = response.data[0]['id']

         # Add points
        points_data = {
            'member_id': member_id,
            'points': int(points_to_add),
            'semester': semester, 
            'reason': 'Event attendance'
        }

        points_response = supabase.table('points_tracking').insert(points_data).execute()
        print(f"Added {points_to_add} points for {name}")
        return points_response.data
    
    except Exception as e:
        raise Exception(f"Error adding/updating points: {str(e)}")

# Get points via the responses object from Google Forms
# This is good to use when collecting responses from an event that copied the base template
def retrieve_event_responses(form_id: str, points_to_add: int):
    try:
        # Get form responses using Google Forms API
        url = f"https://forms.googleapis.com/v1/forms/{form_id}/responses"
        token = get_oauth_token()
        head = {'Authorization': f'Bearer {token}'}
        # head = {'Authorization': 'Bearer {}'.format(os.getenv('GOOGLE_OAUTH_TOKEN'))}
        
        # First, get the form structure to find question IDs
        form_url = f"https://forms.googleapis.com/v1/forms/{form_id}"
        form_request = requests.get(url=form_url, headers=head)
        form_data = json.loads(form_request.text)
        
        print(form_data)

        # Find the question IDs for name and netID
        name_question_id = None
        netid_question_id = None
        
        for item in form_data.get('items', []):
            title = item.get('title', '').lower()
            if 'name' in title:
                name_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'netid' in title:
                netid_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
        
        if not name_question_id or not netid_question_id:
            raise Exception("Could not find name or netID questions in form")

        # Get form responses
        request = requests.get(url=url, headers=head)
        response = json.loads(request.text)
        form_responses = response.get('responses', [])
        
        # Process each response
        for submission in form_responses:
            submission_info = submission.get('answers', {})
            try:
                name = submission_info[name_question_id]['textAnswers']['answers'][0]['value']
                netid = submission_info[netid_question_id]['textAnswers']['answers'][0]['value']
                add_or_update_points(name, netid, points_to_add)
            except KeyError as e:
                print(f"Error processing submission: {e}")
                continue

    except Exception as e:
        raise Exception(f"Error retrieving form responses: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} responses")

main()