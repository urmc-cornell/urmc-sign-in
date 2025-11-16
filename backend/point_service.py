from supabase import create_client
import os
import json
import requests
from dotenv import load_dotenv
import pickle
import os.path
from slack_service import send_points_notification
from datetime import datetime
import pytz
import io
import mimetypes

# Load environment variables
load_dotenv()

# Initialize Supabase client
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

def download_and_upload_headshot(file_id, netid, image_type, credentials, name_for_logging=""):
    """
    Downloads a file from Google Drive and uploads it to Supabase storage
    
    Args:
        file_id: Google Drive file ID
        netid: User's netid for naming
        image_type: 'Primary' or 'Secondary'
        credentials: Google API credentials
        name_for_logging: Name for logging purposes
    
    Returns:
        URL of uploaded file in Supabase storage or None if failed
    """
    try:
        token = credentials.token
        
        # First get file metadata to determine file extension
        metadata_url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        headers = {'Authorization': f'Bearer {token}'}
        
        metadata_response = requests.get(metadata_url, headers=headers)
        if metadata_response.status_code != 200:
            print(f"Failed to get file metadata for {name_for_logging}: {metadata_response.text}")
            return None
            
        metadata = metadata_response.json()
        file_name = metadata.get('name', 'unknown')
        mime_type = metadata.get('mimeType', 'application/octet-stream')
        
        # Determine file extension
        extension = mimetypes.guess_extension(mime_type) or '.jpg'
        if extension == '.jpe':  # Fix common issue with jpeg extension
            extension = '.jpeg'
        
        # Download the file content
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        download_response = requests.get(download_url, headers=headers)
        
        if download_response.status_code != 200:
            print(f"Failed to download file for {name_for_logging}: {download_response.text}")
            return None
        
        # Create file name for Supabase storage
        supabase_filename = f"{netid.lower()}{image_type}{extension}"
        
        # Upload to Supabase storage
        file_bytes = download_response.content
        
        # Try to upload first, if it fails due to duplicate, delete and re-upload
        try:
            upload_response = supabase.storage.from_("headshots").upload(
                f"eboard/{supabase_filename}",
                file_bytes,
                {"content-type": mime_type}
            )
        except Exception as e:
            # If upload fails due to duplicate, delete existing file and re-upload
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                try:
                    # Delete the existing file
                    delete_response = supabase.storage.from_("headshots").remove([f"eboard/{supabase_filename}"])
                    # Re-upload the new file
                    upload_response = supabase.storage.from_("headshots").upload(
                        f"eboard/{supabase_filename}",
                        file_bytes,
                        {"content-type": mime_type}
                    )
                except Exception as replace_e:
                    print(f"Failed to replace headshot for {name_for_logging}: {str(replace_e)}")
                    return None
            else:
                print(f"Failed to upload headshot for {name_for_logging}: {str(e)}")
                return None
        
        # Construct the public URL
        public_url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/headshots/eboard/{supabase_filename}"
        
        print(f"Successfully uploaded {image_type} headshot for {name_for_logging}")
        return public_url
        
    except Exception as e:
        print(f"Error processing headshot for {name_for_logging}: {str(e)}")
        return None

def process_headshot_upload(question_id, submission_info, netid, headshot_type, credentials, name):
    """
    Helper function to process headshot uploads from Google Form submissions
    
    Args:
        question_id: The question ID for the headshot field
        submission_info: The submission data from Google Forms
        netid: User's netid
        headshot_type: 'Primary' or 'Secondary'
        credentials: Google API credentials
        name: User's name for logging
    
    Returns:
        URL of uploaded headshot or None if no file or upload failed
    """
    if not question_id or question_id not in submission_info:
        return None
        
    headshot_data = submission_info.get(question_id, {})
    file_upload_answers = headshot_data.get('fileUploadAnswers', {})
    
    if file_upload_answers and 'answers' in file_upload_answers:
        files = file_upload_answers['answers']
        if files and len(files) > 0:
            file_id = files[0].get('fileId')
            if file_id:
                return download_and_upload_headshot(
                    file_id, netid, headshot_type, credentials, name
                )
    
    return None

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
        print(f"Retrieved and processed {len(form_responses)} event responses")


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
        

        # Find the question IDs for all form fields
        name_question_id = None
        netid_question_id = None
        grad_question_id = None
        position_question_id = None
        bio_question_id = None
        interests_question_id = None
        major_question_id = None
        linkedin_question_id = None
        insta_question_id = None
        headshot_1_question_id = None  # Profile page headshot
        headshot_2_question_id = None  # Secondary picture
        
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
        print(f"Form responses count: {len(form_responses)}")
        
        # Process each response
        for submission in form_responses:
            submission_info = submission.get('answers', {})
            try:
                name = submission_info.get(name_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                netid = submission_info.get(netid_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                grad_date = submission_info.get(grad_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                major = submission_info.get(major_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                position = submission_info.get(position_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                interests = submission_info.get(interests_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                bio = submission_info.get(bio_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                insta = submission_info.get(insta_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)
                linkedin = submission_info.get(linkedin_question_id, {}).get('textAnswers', {}).get('answers', [{}])[0].get('value', None)

                # Process headshot file uploads
                headshot_url = process_headshot_upload(
                    headshot_1_question_id, submission_info, netid, 'Primary', credentials, name
                )
                secondary_headshot_url = process_headshot_upload(
                    headshot_2_question_id, submission_info, netid, 'Secondary', credentials, name
                )

                add_eboard(netid, name, grad_date, major, position, interests, bio, insta, linkedin, headshot_url, secondary_headshot_url)
            except KeyError as e:
                print(f"Error processing submission: {e}")
                continue
            except Exception as e:
                print(f"Error processing submission for {name or 'unknown'}: {str(e)}")
                continue

    except Exception as e:
        raise Exception(f"Error retrieving form responses: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} eboard responses")

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
        print(f"Retrieved and processed {len(form_responses)} ta responses")

def is_integer_string(s):
        try:
            int(s)
            return True
        except ValueError:
            return False

def add_ta(netid: str = None, name: str = None, grad_date: str = None, course: str = None,
           office_hours : str = None, review_session : str = None): 
    try:
        semester = "fa25" 
        member_data = {
                'netid': netid.lower(),
                'first_name': name.split()[0],
                'last_name': name.split()[-1] if len(name.split()) > 1 else '',
                'graduation_year': grad_date if is_integer_string(grad_date) else None,
                # 'course': course,
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
        if "ta" in existing_list:
            data = {'role': existing_list}
        else:
            data = {'role': existing_list + ["ta"]}
        supabase.table("members").update(data).eq("netid", netid.lower()).execute()

        print(f"Added {name} to ta directory")
        return response.data
    
    except Exception as e:
        raise Exception(f"Error adding {name} as a TA: {str(e)}")

def add_eboard(netid: str = None, name: str = None, grad_date: str = None, major: str = None, 
               position: str = None, interests: str = None, bio: str = None, insta=None, linkedin=None,
               headshot_url=None, secondary_headshot_url=None):
    try:
        semester = "fa25" 

        transformed_roles = {
            "Prof Dev": "Professional Development",
            "Professional Development Chair" : "Professional Development",
            "Professional Development Co-Chair" : "Professional Development",
            "Web Dev" : "Web Development",
            "Web Development Chair": "Web Development",
            "Web Development Co-Chair": "Web Development",
            "Fresh" : "Freshman Representative",
            "Freshman Rep" : "Freshman Representative"
        }

        member_data = {
                'netid': netid.lower(),
                'first_name': name.split()[0],
                'last_name': name.split()[-1] if len(name.split()) > 1 else '',
                'graduation_year': grad_date,
                'major': major,
                'position': transformed_roles.get(position, position),
                'role': ["eboard"],
                'ask_about': interests.split(',') if interests else [],
                'bio': bio,
                'linkedin_url': linkedin,
                'instagram_url': insta
            }
        
        # Add headshot URLs if provided
        if headshot_url:
            member_data['headshot_url'] = headshot_url
        if secondary_headshot_url:
            member_data['secondary_headshot_url'] = secondary_headshot_url
        
        response = (
            supabase.table("members")
            .upsert(member_data, on_conflict=["netid"])
            .execute()
            )
    
        print(f"Added {name} to eboard")
        return response.data
    
    except Exception as e:
        pass
        # raise Exception(f"Error adding/updating points for {name}: {str(e)}")
    
    
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
        print(f"Retrieved and processed {len(form_responses)} member responses")


def add_event(name: str = None, description: str = None, flyer_url: str = None, insta=None,
              month: str = None, day: str = None, year: str = None):
    try:
        # Convert date strings to datetime object
        # Assuming month is full name (e.g., "January"), day is string number ("1"), year is string ("2024")
        date_string = f"{month} {day} {year}"
        date_object = datetime.strptime(date_string, "%B %d %Y")
        
        # Make it timezone-aware (using UTC)
        event_date = date_object.replace(tzinfo=pytz.UTC).isoformat()
        semester = "sp25" 

        event_data = {
            'name': name,
            'description': description,
            'flyer_url': flyer_url,
            'instagram_url': insta,
            'date': event_date, 
            'semester':semester
        }

        response = (
            supabase.table("events")
            .insert(event_data)
            .execute()
        )

        print(f"Added event: {name}")
        return response.data
    except Exception as e:
        raise Exception(f"Error adding event {name}: {str(e)}")