from supabase import create_client
import os
import json
import requests
from dotenv import load_dotenv
import pickle
import os.path
from slack_service import send_points_notification

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

def add_or_update_points(netid: str, points_to_add: int, reason: str, name: str = None):
    try:
        semester = "sp25"
        # First check if member exists
        response = supabase.table('members').select('id, email').eq('netid', netid.lower()).execute()

        if not response.data:
            # Member doesn't exist, create new member
            member_data = {
                'netid': netid.lower(),
                'first_name': name.split()[0] if name else '',
                'last_name': name.split()[-1] if name and len(name.split()) > 1 else '',
                'email': f"{netid.lower()}@cornell.edu"
            }
            member_response = supabase.table('members').insert(member_data).execute()
            member_id = member_response.data[0]['id']
            member_email = member_response.data[0]['email']
        else:
            member_id = response.data[0]['id']
            # Default to Cornell email if email field is None or empty
            member_email = response.data[0].get('email') or f"{netid.lower()}@cornell.edu"

        # Add points
        points_data = {
            'member_id': member_id,
            'points': int(points_to_add),
            'semester': semester,
            'reason': reason
        }

        points_response = supabase.table('points_tracking').insert(points_data).execute()
        
        # Send Slack notification
        if member_email:
            send_points_notification(member_email, points_to_add, reason)
            
        print(f"Added {points_to_add} points for {name or netid}")
        return points_response.data
    
    except Exception as e:
        raise Exception(f"Error adding/updating points: {str(e)}")

# Get points via the responses object from Google Forms
# This is good to use when collecting responses from an event that copied the base template
def retrieve_event_responses(form_id: str, points_to_add: int, credentials=None):
    try:
        # If credentials provided, use them. Otherwise use existing token logic
        if not credentials:
            raise ValueError("Credentials are required")
    
        token = credentials.token

        # Get form responses using Google Forms API
        url = f"https://forms.googleapis.com/v1/forms/{form_id}/responses"
        head = {'Authorization': f'Bearer {token}'}
        
        # First, get the form structure to find question IDs
        form_url = f"https://forms.googleapis.com/v1/forms/{form_id}"
        form_request = requests.get(url=form_url, headers=head)
        form_data = json.loads(form_request.text)
        

        # Find the question IDs for name and netID
        name_question_id = None
        netid_question_id = None
        
        # Get the form title
        form_title = form_data.get('info', {}).get('title', 'Unknown Form')
        reason = f"Event Attendance - {form_title}"

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
                add_or_update_points(netid=netid, points_to_add=points_to_add, name=name, reason=reason)
            except KeyError as e:
                print(f"Error processing submission: {e}")
                continue

    except Exception as e:
        raise Exception(f"Error retrieving form responses: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} responses")


def retrieve_eboard_responses(form_id: str, credentials=None):
    try:
        # If credentials provided, use them. Otherwise use existing token logic
        if not credentials:
            raise ValueError("Credentials are required")
    
        token = credentials.token

        # Get form responses using Google Forms API
        url = f"https://forms.googleapis.com/v1/forms/{form_id}/responses"
        head = {'Authorization': f'Bearer {token}'}
        
        # First, get the form structure to find question IDs
        form_url = f"https://forms.googleapis.com/v1/forms/{form_id}"
        form_request = requests.get(url=form_url, headers=head)
        form_data = json.loads(form_request.text)
        

        # Find the question IDs for name and netID
        name_question_id = None
        netid_question_id = None
        grad_question_id = None
        position_question_id = None
        headshot_1_question_id = None
        headshot_2_question_id = None
        bio_question_id = None
        interests_question_id = None
        major_question_id = None

        
        # Get the form title
        form_title = form_data.get('info', {}).get('title', 'Unknown Form')
        # breakpoint()
        for item in form_data.get('items', []):
            title = item.get('title', '').lower()
            if 'name' in title:
                name_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'netid' in title:
                netid_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'Graduation' in title:
                grad_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'position' in title:
                position_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'profile page' in title:
                headshot_1_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'picture' in title:
                headshot_2_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'interested in' in title:
                interests_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'major' in title:
                major_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')

            # elif 'instagram' in title:
            #     insta_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            # elif 'linkedin' in title:
            #     netid_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
        if not name_question_id or not netid_question_id or not grad_question_id or not position_question_id or not headshot_1_question_id or not headshot_2_question_id or not interests_question_id:
            raise Exception("Could not find fields in form")

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
                grad_date = submission_info[grad_question_id]['textAnswers']['answers'][0]['value']
                major = submission_info[major_question_id]['textAnswers']['answers'][0]['value']
                position = submission_info[position_question_id]['textAnswers']['answers'][0]['value']
                interests = submission_info[interests_question_id]['textAnswers']['answers'][0]['value']
                # netid = submission_info[netid_question_id]['textAnswers']['answers'][0]['value']
                # netid = submission_info[netid_question_id]['textAnswers']['answers'][0]['value']
                add_eboard(netid, name, grad_date, major, position, interests)
            except KeyError as e:
                print(f"Error processing submission: {e}")
                continue

    except Exception as e:
        raise Exception(f"Error retrieving form responses: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} responses")



def add_eboard(netid: str, name: str = None, grad_date: str = None, major: str = None, 
               position: str = None, interests: str = None):
    print(f"netid {netid}")
    print("name " + name)
    print("grad date " + grad_date)
    print("major " + major)
    print("position " + position)
    print("interests " + interests)
    # try:
    #     semester = "sp25" 
    #     # First check if member exists
    #     response = supabase.table('members').select('id').eq('netid', netid.lower()).execute()

    #     if not response.data:
    #         # Member doesn't exist, create new member
    #         member_data = {
    #             'netid': netid.lower(),
    #             'first_name': name.split()[0],
    #             'last_name': name.split()[-1] if len(name.split()) > 1 else '',
    #         }
    #         member_response = supabase.table('members').insert(member_data).execute()
    #         member_id = member_response.data[0]['id']
    #     else:
    #         member_id = response.data[0]['id']
    #         points_response = supabase.table('points_tracking').insert(member_data).execute()
    #     print(f"Added {name} to eboard")
    #     return points_response.data
    
    # except Exception as e:
    #     raise Exception(f"Error adding/updating points: {str(e)}")
    
    
# Get points via the responses object from Google Forms
# This is good to use when collecting responses from an event that copied the base template
def add_members(form_id: str, points_to_add: int, credentials=None):
    try:
        # If credentials provided, use them. Otherwise use existing token logic
        if not credentials:
            raise ValueError("Credentials are required")
    
        token = credentials.token

        # Get form responses using Google Forms API
        url = f"https://forms.googleapis.com/v1/forms/{form_id}/responses"
        head = {'Authorization': f'Bearer {token}'}
        
        # First, get the form structure to find question IDs
        form_url = f"https://forms.googleapis.com/v1/forms/{form_id}"
        form_request = requests.get(url=form_url, headers=head)
        form_data = json.loads(form_request.text)
        

        # Find the question IDs for name and netID
        name_question_id = None
        netid_question_id = None
        
        # Get the form title
        form_title = form_data.get('info', {}).get('title', 'Unknown Form')
        reason = f"Event Attendance - {form_title}"

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
                add_or_update_points(netid=netid, points_to_add=points_to_add, name=name, reason=reason)
            except KeyError as e:
                print(f"Error processing submission: {e}")
                continue

    except Exception as e:
        raise Exception(f"Error retrieving form responses: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} responses")
