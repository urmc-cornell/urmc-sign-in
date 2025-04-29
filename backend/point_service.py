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
        # Check if environment variables are set
        if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_KEY"):
            raise Exception("Missing Supabase environment variables. Check your .env file.")
        
        semester = "sp25"
        # First check if member exists
        try:
            response = supabase.table('members').select('id, email').eq('netid', netid.lower()).execute()
        except Exception as db_err:
            raise Exception(f"Supabase connection error: {str(db_err)}")

        if not response.data:
            # Member doesn't exist, create new member
            member_data = {
                'netid': netid.lower(),
                'first_name': name.split()[0] if name else '',
                'last_name': name.split()[-1] if name and len(name.split()) > 1 else '',
                'email': f"{netid.lower()}@cornell.edu"
            }
            try:
                member_response = supabase.table('members').insert(member_data).execute()
                member_id = member_response.data[0]['id']
                member_email = member_response.data[0]['email']
            except Exception as insert_err:
                raise Exception(f"Error creating new member: {str(insert_err)}")
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

        try:
            points_response = supabase.table('points_tracking').insert(points_data).execute()
        except Exception as points_err:
            raise Exception(f"Error inserting points data: {str(points_err)}")
        
        # Send Slack notification
        if member_email:
            try:
                send_points_notification(member_email, points_to_add, reason)
            except Exception as slack_err:
                print(f"Warning: Slack notification failed: {str(slack_err)}")
                # Continue execution even if Slack notification fails
            
        print(f"Added {points_to_add} points for {name or netid}")
        return points_response.data
    
    except Exception as e:
        print(f"Detailed error in add_or_update_points: {str(e)}")
        raise Exception(f"Error adding/updating points: {str(e)}")

# Get points via the responses object from Google Forms
# This is good to use when collecting responses from an event that copied the base template
def retrieve_event_responses(form_id: str, points_to_add: int, credentials=None):
    try:
        # If credentials provided, use them. Otherwise use existing token logic
        if not credentials:
            raise ValueError("Credentials are required")
        
        try:
            token = credentials.token
        except Exception as cred_err:
            raise Exception(f"Error accessing credentials token: {str(cred_err)}")

        # Get form responses using Google Forms API
        url = f"https://forms.googleapis.com/v1/forms/{form_id}/responses"
        head = {'Authorization': f'Bearer {token}'}
        
        # First, get the form structure to find question IDs
        form_url = f"https://forms.googleapis.com/v1/forms/{form_id}"
        try:
            form_request = requests.get(url=form_url, headers=head)
            if form_request.status_code != 200:
                raise Exception(f"Form API request failed with status {form_request.status_code}: {form_request.text}")
            form_data = json.loads(form_request.text)
        except requests.RequestException as req_err:
            raise Exception(f"Error requesting form data: {str(req_err)}")
        except json.JSONDecodeError as json_err:
            raise Exception(f"Error parsing form data JSON: {str(json_err)}")
        
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
            raise Exception("Could not find name or netID questions in form. Form structure may be incorrect.")

        # Get form responses
        try:
            request = requests.get(url=url, headers=head)
            if request.status_code != 200:
                raise Exception(f"Form responses API request failed with status {request.status_code}: {request.text}")
            response = json.loads(request.text)
        except requests.RequestException as req_err:
            raise Exception(f"Error requesting form responses: {str(req_err)}")
        except json.JSONDecodeError as json_err:
            raise Exception(f"Error parsing form responses JSON: {str(json_err)}")
            
        form_responses = response.get('responses', [])
        
        if not form_responses:
            print("Warning: No form responses found")
        
        # Process each response
        processed_count = 0
        error_count = 0
        for submission in form_responses:
            submission_info = submission.get('answers', {})
            try:
                name = submission_info[name_question_id]['textAnswers']['answers'][0]['value']
                netid = submission_info[netid_question_id]['textAnswers']['answers'][0]['value']
                # Clean the netid
                netid = netid.strip()
                if '@cornell.edu' in netid:
                    netid = netid.split('@')[0]
                add_or_update_points(netid=netid, points_to_add=points_to_add, name=name, reason=reason)
                processed_count += 1
            except KeyError as e:
                print(f"Error processing submission: Missing field {e}")
                error_count += 1
                continue
            except Exception as e:
                print(f"Error processing submission for {submission_info.get('name', 'unknown')}: {str(e)}")
                error_count += 1
                continue

        print(f"Processed {processed_count} responses successfully, {error_count} errors")

    except Exception as e:
        print(f"Detailed error in retrieve_event_responses: {str(e)}")
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
        bio_question_id = None
        interests_question_id = None
        major_question_id = None
        linkedin_question_id = None
        insta_question_id = None
        
        for item in form_data.get('items', []):
            title = item.get('title', '').lower()
            print(title)
            if 'name' in title:
                name_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'netid' in title:
                netid_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'graduation' in title:
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
            elif 'instagram' in title:
                insta_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'linkedin' in title:
                linkedin_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'short bio' in title:
                bio_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')

        # Get form responses
        request = requests.get(url=url, headers=head)
        response = json.loads(request.text)
        form_responses = response.get('responses', [])
        
        # Process each response
        for submission in form_responses:
            submission_info = submission.get('answers', {})
            try:
                name = submission_info.get(name_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                netid = submission_info.get(netid_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                # Clean the netid if it exists
                if netid:
                    netid = netid.strip()
                    if '@cornell.edu' in netid:
                        netid = netid.split('@')[0]
                
                grad_date = submission_info.get(grad_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                major = submission_info.get(major_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                position = submission_info.get(position_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                interests = submission_info.get(interests_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                bio = submission_info.get(bio_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                insta = submission_info.get(insta_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                linkedin = submission_info.get(linkedin_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)

                add_eboard(netid, name, grad_date, major, position, interests, bio, insta, linkedin)
            except KeyError as e:
                print(f"Error processing submission: {e}")
                continue

    except Exception as e:
        raise Exception(f"Error retrieving form responses: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} responses")

def retrieve_ta_responses(form_id: str, credentials=None):
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
        class_question_id = None
        office_hours_question_id = None
        review_session_question_id = None
        
        for item in form_data.get('items', []):
            title = item.get('title', '').lower()
            print(title)
            if 'name' in title:
                name_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'netid' in title:
                netid_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'year' in title:
                grad_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'course' in title:
                class_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'office' in title:
                office_hours_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'review' in title:
                review_session_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')

        # Get form responses
        request = requests.get(url=url, headers=head)
        response = json.loads(request.text)
        form_responses = response.get('responses', [])
        
        # Process each response
        for submission in form_responses:
            submission_info = submission.get('answers', {})
            try:
                name = submission_info.get(name_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                netid = submission_info.get(netid_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                # Clean the netid if it exists
                if netid:
                    netid = netid.strip()
                    if '@cornell.edu' in netid:
                        netid = netid.split('@')[0]

                grad_date = submission_info.get(grad_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                course = submission_info.get(class_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                office_hours = submission_info.get(office_hours_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                review_session = submission_info.get(review_session_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)

                add_ta(netid, name, grad_date, course, office_hours, review_session)
            except KeyError as e:
                print(f"Error processing submission: {e}")
                continue

    except Exception as e:
        raise Exception(f"Error retrieving form responses: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} responses")

def add_ta(netid: str = None, name: str = None, grad_date: str = None, course: str = None,
           office_hours : str = None, review_session : str = None):
    try:
        semester = "sp25" 
        member_data = {
                'netid': netid.lower(),
                'first_name': name.split()[0],
                'last_name': name.split()[-1] if len(name.split()) > 1 else '',
                'graduation_year': grad_date,
                'course': course,
                'office_hours': office_hours,
                'review_sessions': review_session,
                'ta_semester': semester
            }
        
        response = (
            supabase.table("members")
            .upsert(member_data, on_conflict=["netid"])
            .execute()
            )
    
        row = supabase.table("members").select("role").eq("netid", netid.lower()).single().execute()
        if row.data:
            existing_list = row.data["role"] or []  # Handle NULL case
        else:
            existing_list = []
        data = {'role': existing_list + ["ta"]}
        supabase.table("members").update(data).eq("netid", netid.lower()).execute()

        print(f"Added {name} to ta directory")
        return response.data
    
    except Exception as e:
        raise Exception(f"Error adding {name} as a TA: {str(e)}")

def add_eboard(netid: str = None, name: str = None, grad_date: str = None, major: str = None, 
               position: str = None, interests: str = None, bio: str = None, insta=None, linkedin=None):
    try:
        semester = "sp25" 
        member_data = {
                'netid': netid.lower(),
                'first_name': name.split()[0],
                'last_name': name.split()[-1] if len(name.split()) > 1 else '',
                'graduation_year': grad_date,
                'major': major,
                'position': position,
                'role': ["member"],
                'ask_about': interests.split(','),
                'bio': bio,
                'linkedin_url': linkedin,
                'instagram_url': insta
            }
        
        response = (
            supabase.table("members")
            .upsert(member_data, on_conflict=["netid"])
            .execute()
            )
    
        print(f"Added {name} to eboard")
        return response.data
    
    except Exception as e:
        raise Exception(f"Error adding/updating points for {name}: {str(e)}")
    
    
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
                # Clean the netid
                netid = netid.strip()
                if '@cornell.edu' in netid:
                    netid = netid.split('@')[0]
                add_or_update_points(netid=netid, points_to_add=points_to_add, name=name, reason=reason)
            except KeyError as e:
                print(f"Error processing submission: {e}")
                continue

    except Exception as e:
        raise Exception(f"Error retrieving form responses: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} responses")

def update_member_info(form_id: str, credentials=None):
    """
    Update member information (year and major) from a Google Form.
    This function processes form responses and updates the database with year and major information
    if it doesn't already exist for that member.
    """
    try:
        # If credentials provided, use them. Otherwise use existing token logic
        if not credentials:
            raise ValueError("Credentials are required")
        
        try:
            token = credentials.token
        except Exception as cred_err:
            raise Exception(f"Error accessing credentials token: {str(cred_err)}")

        # Get form responses using Google Forms API
        url = f"https://forms.googleapis.com/v1/forms/{form_id}/responses"
        head = {'Authorization': f'Bearer {token}'}
        
        # First, get the form structure to find question IDs
        form_url = f"https://forms.googleapis.com/v1/forms/{form_id}"
        try:
            form_request = requests.get(url=form_url, headers=head)
            if form_request.status_code != 200:
                raise Exception(f"Form API request failed with status {form_request.status_code}: {form_request.text}")
            form_data = json.loads(form_request.text)
        except requests.RequestException as req_err:
            raise Exception(f"Error requesting form data: {str(req_err)}")
        except json.JSONDecodeError as json_err:
            raise Exception(f"Error parsing form data JSON: {str(json_err)}")
        
        # Find the question IDs for name, netID, year, and major
        name_question_id = None
        netid_question_id = None
        year_question_id = None
        major_question_id = None
        
        for item in form_data.get('items', []):
            title = item.get('title', '').lower()
            if 'name' in title:
                name_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'netid' in title:
                netid_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'year' in title:
                year_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'major' in title:
                major_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
        
        if not name_question_id or not netid_question_id:
            raise Exception("Could not find name or netID questions in form. Form structure may be incorrect.")
        
        if not year_question_id and not major_question_id:
            raise Exception("Could not find year or major questions in form. Form structure may be incorrect.")

        # Get form responses
        try:
            request = requests.get(url=url, headers=head)
            if request.status_code != 200:
                raise Exception(f"Form responses API request failed with status {request.status_code}: {request.text}")
            response = json.loads(request.text)
        except requests.RequestException as req_err:
            raise Exception(f"Error requesting form responses: {str(req_err)}")
        except json.JSONDecodeError as json_err:
            raise Exception(f"Error parsing form responses JSON: {str(json_err)}")
            
        form_responses = response.get('responses', [])
        
        if not form_responses:
            print("Warning: No form responses found")
        
        # Year mapping dictionary
        year_to_graduation = {
            "freshman": 2028,
            "sophomore": 2027,
            "junior": 2026,
            "senior": 2025
        }
        
        # Major mapping dictionary
        major_to_full_name = {
            "cs": "Computer Science",
            "ece": "Electrical and Computer Engineering",
            "is/isst": "Information Science",
            "orie": "Operations Research and Information Engineering"
        }
        
        # Process each response
        processed_count = 0
        error_count = 0
        for submission in form_responses:
            submission_info = submission.get('answers', {})
            try:
                name = submission_info.get(name_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', '')
                netid = submission_info.get(netid_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', '')
                
                # Clean the netid
                if netid:
                    netid = netid.strip()
                    if '@cornell.edu' in netid:
                        netid = netid.split('@')[0]
                else:
                    continue  # Skip if no netid
                
                # Get year and major if the questions exist
                year_raw = None
                major_raw = None
                
                if year_question_id:
                    year_raw = submission_info.get(year_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', '')
                
                if major_question_id:
                    major_raw = submission_info.get(major_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', '')
                
                # Map year to graduation year
                graduation_year = None
                if year_raw:
                    year_raw = year_raw.lower()
                    graduation_year = year_to_graduation.get(year_raw)
                
                # Map major to full name
                full_major = None
                if major_raw:
                    major_raw = major_raw.lower()
                    full_major = major_to_full_name.get(major_raw, major_raw)
                
                # Check if member exists and if we need to update
                response = supabase.table('members').select('id, graduation_year, major').eq('netid', netid.lower()).execute()
                
                if response.data:
                    member_id = response.data[0]['id']
                    current_grad_year = response.data[0].get('graduation_year')
                    current_major = response.data[0].get('major')
                    
                    update_data = {}
                    
                    if graduation_year and not current_grad_year:
                        update_data['graduation_year'] = graduation_year
                    
                    if full_major and not current_major:
                        update_data['major'] = full_major
                    
                    if update_data:
                        supabase.table('members').update(update_data).eq('id', member_id).execute()
                        print(f"Updated info for {name} ({netid})")
                else:
                    # Member doesn't exist, create new
                    member_data = {
                        'netid': netid.lower(),
                        'first_name': name.split()[0] if name else '',
                        'last_name': name.split()[-1] if name and len(name.split()) > 1 else '',
                        'email': f"{netid.lower()}@cornell.edu"
                    }
                    
                    if graduation_year:
                        member_data['graduation_year'] = graduation_year
                    
                    if full_major:
                        member_data['major'] = full_major
                    
                    supabase.table('members').insert(member_data).execute()
                    print(f"Created new member {name} ({netid}) with provided info")
                
                processed_count += 1
                
            except KeyError as e:
                print(f"Error processing submission: Missing field {e}")
                error_count += 1
                continue
            except Exception as e:
                print(f"Error processing submission for {submission_info.get('name', 'unknown')}: {str(e)}")
                error_count += 1
                continue

        print(f"Processed {processed_count} responses successfully, {error_count} errors")

    except Exception as e:
        print(f"Detailed error in update_member_info: {str(e)}")
        raise Exception(f"Error updating member info: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} responses")
