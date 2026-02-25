import os
import re
import json
import requests
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
import pickle
import os.path
from slack_service import send_points_notification
from supabase_clients import get_client, get_supabase_url
from datetime import datetime
import pytz
import io
import mimetypes
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
register_heif_opener()  # Adds HEIC/HEIF support to Pillow

# Load environment variables
load_dotenv()

def _check_google_api_response(resp, context="API request"):
    """Check a Google API response and raise a clear error for common failures."""
    if resp.status_code == 401:
        raise Exception("Your Google session has expired. Please log out and log back in.")
    if resp.status_code == 403:
        raise Exception("Access denied. Try logging out and back in to refresh permissions, or make sure you have edit access.")
    if resp.status_code == 404:
        raise Exception("Not found. Double-check the ID or link.")
    if resp.status_code != 200:
        raise Exception(f"{context} failed (status {resp.status_code}): {resp.text[:200]}")

def crop_image_to_square(image_bytes):
    """
    Crops an image to a square, focusing on the upper-middle portion for face-centered cropping.
    If the image is already square, returns it unchanged.
    
    Args:
        image_bytes: Raw image bytes
    
    Returns:
        Cropped image bytes as JPEG
    """
    try:
        # Load image from bytes
        img = Image.open(io.BytesIO(image_bytes))

        # Apply EXIF orientation so phone photos aren't sideways
        img = ImageOps.exif_transpose(img)

        # Convert to RGB if necessary (handles RGBA, grayscale, etc.)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        width, height = img.size
        
        # If already square, resize if needed and return
        if width == height:
            max_size = 800
            if img.width > max_size:
                img = img.resize((max_size, max_size), Image.LANCZOS)
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=85)
            return output.getvalue()
        
        # Determine square size (use smaller dimension)
        square_size = min(width, height)
        
        # Calculate crop coordinates
        if width > height:
            # Landscape: center horizontally, bias towards top for faces
            left = (width - square_size) // 2
            top = 0  # Start from top
            right = left + square_size
            bottom = square_size
        else:
            # Portrait: center horizontally, focus on upper portion (where faces typically are)
            left = (width - square_size) // 2
            top = int((height - square_size) * 0.15)  # Start 15% from top to capture face
            right = left + square_size
            bottom = top + square_size
        
        # Crop the image
        cropped_img = img.crop((left, top, right, bottom))

        # Resize to max 800x800 for fast loading
        max_size = 800
        if cropped_img.width > max_size:
            cropped_img = cropped_img.resize((max_size, max_size), Image.LANCZOS)

        # Convert back to bytes
        output = io.BytesIO()
        cropped_img.save(output, format='JPEG', quality=85)
        
        return output.getvalue()
        
    except Exception as e:
        print(f"Error cropping image: {str(e)}")
        # If cropping fails, return original bytes
        return image_bytes

def download_and_upload_headshot(file_id, netid, image_type, credentials, name_for_logging="", env="production"):
    """
    Downloads a file from Google Drive and uploads it to Supabase storage

    Args:
        file_id: Google Drive file ID
        netid: User's netid for naming
        image_type: 'Primary' or 'Secondary'
        credentials: Google API credentials
        name_for_logging: Name for logging purposes
        env: 'staging' or 'production'

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
        
        # Process image: crop to square and convert to JPEG (handles HEIC, PNG, etc.)
        file_bytes = download_response.content
        file_bytes = crop_image_to_square(file_bytes)
        # crop_image_to_square always outputs JPEG, so force extension and mime
        extension = '.jpeg'
        mime_type = 'image/jpeg'
        supabase_filename = f"{netid.lower()}{image_type}{extension}"

        # Try to upload first, if it fails due to duplicate, delete and re-upload
        sb = get_client(env)
        try:
            upload_response = sb.storage.from_("headshots").upload(
                f"eboard/{supabase_filename}",
                file_bytes,
                {"content-type": mime_type}
            )
        except Exception as e:
            # If upload fails due to duplicate, delete existing file and re-upload
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                try:
                    # Delete the existing file
                    delete_response = sb.storage.from_("headshots").remove([f"eboard/{supabase_filename}"])
                    # Re-upload the new file
                    upload_response = sb.storage.from_("headshots").upload(
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
        public_url = f"{get_supabase_url(env)}/storage/v1/object/public/headshots/eboard/{supabase_filename}"
        
        print(f"Successfully uploaded {image_type} headshot for {name_for_logging}")
        return public_url
        
    except Exception as e:
        print(f"Error processing headshot for {name_for_logging}: {str(e)}")
        return None

def process_headshot_upload(question_id, submission_info, netid, headshot_type, credentials, name, env="production"):
    """
    Helper function to process headshot uploads from Google Form submissions

    Args:
        question_id: The question ID for the headshot field
        submission_info: The submission data from Google Forms
        netid: User's netid
        headshot_type: 'Primary' or 'Secondary'
        credentials: Google API credentials
        name: User's name for logging
        env: 'staging' or 'production'

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
                    file_id, netid, headshot_type, credentials, name, env=env
                )
    
    return None

def add_or_update_points(netid: str, points_to_add: int, reason: str, name: str = None, env: str = "production"):
    try:
        sb = get_client(env)

        semester = "sp25"
        # First check if member exists
        try:
            response = sb.table('members').select('id, email').eq('netid', netid.lower()).execute()
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
                member_response = sb.table('members').insert(member_data).execute()
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
            points_response = sb.table('points_tracking').insert(points_data).execute()
        except Exception as points_err:
            raise Exception(f"Error inserting points data: {str(points_err)}")

        # Send Slack notification (skip in staging to avoid DMing real users)
        if member_email and env == "production":
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
def retrieve_event_responses(form_id: str, points_to_add: int, credentials=None, env: str = "production"):
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
                add_or_update_points(netid=netid, points_to_add=points_to_add, name=name, reason=reason, env=env)
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


def retrieve_eboard_responses(form_id: str, credentials=None, env: str = "production"):
    try:
        # ========== TEST MODE ==========
        # Add netids here to ONLY update these specific people
        # Leave empty [] to process ALL responses (normal mode)
        TEST_NETIDS = []  # Example: ['ta375', 'ye38']
        # ===============================
        
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
        _check_google_api_response(form_request, "Form structure request")
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
            # More specific matching to avoid conflicts (order matters - check specific before general)
            if 'full name' in title:
                name_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'netid' in title or 'net id' in title:
                netid_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'graduation' in title or 'grad' in title:
                grad_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'position' in title or 'role' in title or 'title' in title:
                position_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'headshot' in title and 'second' not in title:
                headshot_1_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'second' in title and ('photo' in title or 'picture' in title or 'headshot' in title):
                headshot_2_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'interested in' in title or 'ask about' in title:
                interests_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'majors and year' in title:
                major_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'instagram' in title:
                insta_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'linkedin' in title:
                linkedin_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')
            elif 'short bio' in title or 'bio' in title:
                bio_question_id = item.get('questionItem', {}).get('question', {}).get('questionId')

        print(f"Headshot 1 question ID: {headshot_1_question_id}")
        print(f"Headshot 2 question ID: {headshot_2_question_id}")

        # Get form responses
        request = requests.get(url=url, headers=head)
        _check_google_api_response(request, "Form responses request")
        response = json.loads(request.text)
        form_responses = response.get('responses', [])
        print(f"Form responses count: {len(form_responses)}")
        
        if TEST_NETIDS:
            print(f"🧪 TEST MODE: Only processing netids: {TEST_NETIDS}")
        
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
                
                # Clean up all text fields: remove trailing/leading whitespace
                name = name.strip() if name else None
                netid = netid.strip() if netid else None
                grad_date = grad_date.strip() if grad_date else None
                major = major.strip() if major else None
                position = position.strip() if position else None
                bio = bio.strip() if bio else None
                insta = insta.strip() if insta else None
                linkedin = linkedin.strip() if linkedin else None
                
                # Skip if TEST_NETIDS is set and this netid is not in the list
                if TEST_NETIDS and netid and netid.lower() not in [n.lower() for n in TEST_NETIDS]:
                    print(f"⏭️  Skipping {netid} (not in test list)")
                    continue
                
                # Clean up interests field: remove trailing commas, extra spaces, empty items
                if interests:
                    # Strip leading/trailing whitespace and commas
                    interests = interests.strip().strip(',').strip()
                    # Split by comma, strip each item, and filter out empty items
                    interests_list = [item.strip() for item in interests.split(',') if item.strip()]
                    # Rejoin with comma-space for consistency
                    interests = ', '.join(interests_list) if interests_list else None

                # Process headshot file uploads
                headshot_url = process_headshot_upload(
                    headshot_1_question_id, submission_info, netid, 'Primary', credentials, name, env=env
                )
                secondary_headshot_url = process_headshot_upload(
                    headshot_2_question_id, submission_info, netid, 'Secondary', credentials, name, env=env
                )

                add_eboard(netid, name, grad_date, major, position, interests, bio, insta, linkedin, headshot_url, secondary_headshot_url, env=env)
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

def _extract_drive_file_id(url_str):
    """Extract Google Drive file ID from a Drive URL."""
    if not url_str or not url_str.strip():
        return None
    url_str = url_str.strip()
    # Handle https://drive.google.com/open?id=FILE_ID
    if 'drive.google.com' in url_str:
        parsed = urlparse(url_str)
        qs = parse_qs(parsed.query)
        if 'id' in qs:
            return qs['id'][0]
        # Handle https://drive.google.com/file/d/FILE_ID/view
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url_str)
        if match:
            return match.group(1)
    return None

def retrieve_eboard_from_sheet(sheet_id: str, credentials=None, env: str = "production"):
    """Process eboard members from a Google Sheet (same columns as the form responses)."""
    try:
        if not credentials:
            raise ValueError("Credentials are required")

        token = credentials.token
        headers = {'Authorization': f'Bearer {token}'}

        # Get spreadsheet metadata to find all sheet names
        meta_url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}?fields=sheets.properties"
        meta_resp = requests.get(meta_url, headers=headers)
        _check_google_api_response(meta_resp, "Google Sheets metadata request")
        sheets_info = meta_resp.json().get('sheets', [])

        # Use the first sheet by default
        sheet_name = sheets_info[0]['properties']['title'] if sheets_info else 'Sheet1'
        print(f"Reading from sheet tab: '{sheet_name}'")

        # Read all data from that sheet
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/'{sheet_name}'!A:Z"
        resp = requests.get(url, headers=headers)
        _check_google_api_response(resp, "Google Sheets request")
        data = resp.json()
        rows = data.get('values', [])

        if len(rows) < 2:
            raise Exception("Sheet has no data rows (only header or empty).")

        # Map column headers to indices using same fuzzy matching as form version
        header = [h.lower().strip() for h in rows[0]]
        col = {}
        for i, title in enumerate(header):
            if 'full name' in title or ('name' in title and 'net' not in title and 'instagram' not in title and 'linkedin' not in title and 'position' not in title):
                col.setdefault('name', i)
            elif 'netid' in title or 'net id' in title:
                col.setdefault('netid', i)
            elif 'graduation' in title or ('grad' in title and 'instagram' not in title):
                col.setdefault('grad', i)
            elif 'position' in title or 'role' in title or 'title' in title:
                col.setdefault('position', i)
            elif 'headshot' in title and 'second' not in title:
                col.setdefault('headshot1', i)
            elif 'second' in title and ('photo' in title or 'picture' in title or 'headshot' in title):
                col.setdefault('headshot2', i)
            elif 'interested in' in title or 'ask about' in title:
                col.setdefault('interests', i)
            elif 'majors and year' in title or ('major' in title and 'year' in title):
                col.setdefault('major', i)
            elif 'instagram' in title:
                col.setdefault('insta', i)
            elif 'linkedin' in title:
                col.setdefault('linkedin', i)
            elif 'short bio' in title or 'bio' in title:
                col.setdefault('bio', i)

        print(f"Sheet headers: {header}")
        print(f"Sheet columns mapped: {col}")
        print(f"Sheet data rows: {len(rows) - 1}")

        if 'name' not in col or 'netid' not in col:
            raise Exception(f"Could not find name or netid columns in sheet headers: {rows[0]}")

        def get_cell(row, key):
            idx = col.get(key)
            if idx is None or idx >= len(row):
                return None
            val = row[idx].strip() if row[idx] else None
            return val

        processed = 0
        errors = 0
        for row in rows[1:]:
            try:
                name = get_cell(row, 'name')
                netid = get_cell(row, 'netid')
                if not netid:
                    continue

                grad_date = get_cell(row, 'grad')
                major = get_cell(row, 'major')
                position = get_cell(row, 'position')
                interests = get_cell(row, 'interests')
                bio = get_cell(row, 'bio')
                insta = get_cell(row, 'insta')
                linkedin = get_cell(row, 'linkedin')

                # Process headshots from Drive links
                headshot_url = None
                headshot1_link = get_cell(row, 'headshot1')
                if headshot1_link:
                    file_id = _extract_drive_file_id(headshot1_link)
                    if file_id:
                        headshot_url = download_and_upload_headshot(
                            file_id, netid, 'Primary', credentials, name or netid, env=env
                        )

                secondary_headshot_url = None
                headshot2_link = get_cell(row, 'headshot2')
                if headshot2_link:
                    file_id = _extract_drive_file_id(headshot2_link)
                    if file_id:
                        secondary_headshot_url = download_and_upload_headshot(
                            file_id, netid, 'Secondary', credentials, name or netid, env=env
                        )

                add_eboard(netid, name, grad_date, major, position, interests, bio, insta, linkedin, headshot_url, secondary_headshot_url, env=env)
                processed += 1
            except Exception as e:
                print(f"Error processing row for {get_cell(row, 'name') or 'unknown'}: {str(e)}")
                errors += 1
                continue

        print(f"Sheet processing complete: {processed} succeeded, {errors} errors")

    except Exception as e:
        raise Exception(f"Error processing sheet: {str(e)}")

def retrieve_ta_responses(form_id: str, credentials=None, env: str = "production"):
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
        _check_google_api_response(form_request, "Form structure request")
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
        _check_google_api_response(request, "Form responses request")
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

                add_ta(netid, name, grad_date, course, office_hours, review_session, env=env)
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
           office_hours : str = None, review_session : str = None, env: str = "production"):
    try:
        sb = get_client(env)
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
            sb.table("members")
            .upsert(member_data, on_conflict=["netid"])
            .execute()
            )

        row = sb.table("members").select("role").eq("netid", netid.lower()).single().execute()
        if row.data:
            existing_list = row.data["role"] or []  # Handle NULL case
        else:
            existing_list = []
        if "ta" in existing_list:
            data = {'role': existing_list}
        else:
            data = {'role': existing_list + ["ta"]}
        sb.table("members").update(data).eq("netid", netid.lower()).execute()

        print(f"Added {name} to ta directory")
        return response.data
    
    except Exception as e:
        raise Exception(f"Error adding {name} as a TA: {str(e)}")

def normalize_position(position: str) -> str:
    """
    Normalize and standardize position/role names.
    
    - Removes "Chair" and "Co-Chair" suffixes
    - Standardizes abbreviations to full role names
    - First tries exact match, then falls back to substring matching
    - Handles case-insensitive matching
    
    Args:
        position: Raw position string from form
        
    Returns:
        Standardized position name
    """
    if not position:
        return position
    
    # Strip whitespace
    position = position.strip()
    
    # Remove "Chair" or "Co-Chair" from the end (case-insensitive)
    if position.lower().endswith(" chair"):
        position = position[:-6].strip()
    elif position.lower().endswith(" co-chair"):
        position = position[:-9].strip()
    
    # Role mapping dictionary - maps common abbreviations/variations to standardized names
    role_mapping = {
        # President variations (check first to avoid conflicts)
        "president": "President",
        "co-president": "Co-President",
        "pres": "President",
        
        # Professional Development variations
        "prof dev": "Professional Development",
        "prof": "Professional Development",
        "professional dev": "Professional Development",
        "profdev": "Professional Development",
        
        # Design variations
        "des": "Design",
        
        # Web Development variations
        "web dev": "Web Development",
        "webdev": "Web Development",
        "web": "Web Development",
        
        # Academic variations
        "acad": "Academic",
        
        # Public Relations variations
        "pr": "Public Relations",
        "public rel": "Public Relations",
        "pubrel": "Public Relations",
        
        # Mentorship variations
        "mentor": "Mentorship",
        
        # Events variations
        "event": "Events",
        
        # Social variations
        "soc": "Social",
        
        # Outreach variations
        "out": "Outreach",
        
        # Freshman Representative variations
        "fresh": "Freshman Representative",
        "freshman rep": "Freshman Representative",
        "frosh": "Freshman Representative",
        
        # Exact matches (for completeness)
        "professional development": "Professional Development",
        "design": "Design",
        "web development": "Web Development",
        "academic": "Academic",
        "alumni": "Alumni",
        "corporate": "Corporate",
        "events": "Events",
        "mentorship": "Mentorship",
        "outreach": "Outreach",
        "public relations": "Public Relations",
        "secretary": "Secretary",
        "social": "Social",
        "treasurer": "Treasurer",
    }
    
    position_lower = position.lower()
    
    # First try: Exact match (case-insensitive)
    if position_lower in role_mapping:
        return role_mapping[position_lower]
    
    # Second try: Substring matching - check if position contains any key
    # Ordered by specificity (longer/more specific keys first)
    # Note: Very short abbreviations like "pr" are excluded to avoid false matches
    substring_keys = [
        ("co-president", "Co-President"),
        ("president", "President"),
        ("professional dev", "Professional Development"),
        ("prof dev", "Professional Development"),
        ("profdev", "Professional Development"),
        ("public rel", "Public Relations"),
        ("pubrel", "Public Relations"),
        ("web dev", "Web Development"),
        ("webdev", "Web Development"),
        ("freshman rep", "Freshman Representative"),
        ("prof", "Professional Development"),
        ("fresh", "Freshman Representative"),
        ("frosh", "Freshman Representative"),
        ("pres", "President"),
        ("acad", "Academic"),
        ("mentor", "Mentorship"),
        ("event", "Events"),
        ("outreach", "Outreach"),
        ("des", "Design"),
        ("web", "Web Development"),
        ("soc", "Social"),
        # "pr" removed from substring to avoid matching "president"
        # "out" removed as it's too short and might match unintended words
    ]
    
    for key, standardized_name in substring_keys:
        if key in position_lower:
            return standardized_name
    
    # Return original if no match found
    return position

def add_eboard(netid: str = None, name: str = None, grad_date: str = None, major: str = None,
               position: str = None, interests: str = None, bio: str = None, insta=None, linkedin=None,
               headshot_url=None, secondary_headshot_url=None, env: str = "production"):
    try:
        sb = get_client(env)
        semester = "sp26"

        # Handle name parsing safely
        first_name = ''
        last_name = ''
        if name:
            name_parts = name.split()
            first_name = name_parts[0] if name_parts else ''
            last_name = name_parts[-1] if len(name_parts) > 1 else ''

        # Normalize the position
        normalized_position = normalize_position(position)

        member_data = {
                'netid': netid.lower() if netid else '',
                'first_name': first_name,
                'last_name': last_name,
                'graduation_year': grad_date,
                'major': major,
                'position': normalized_position,
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
            sb.table("members")
            .upsert(member_data, on_conflict=["netid"])
            .execute()
            )

        # Add "eboard" to role list without overwriting existing roles
        row = sb.table("members").select("role").eq("netid", (netid.lower() if netid else '')).single().execute()
        existing_list = row.data["role"] or [] if row.data else []
        if "eboard" not in existing_list:
            sb.table("members").update({"role": existing_list + ["eboard"]}).eq("netid", (netid.lower() if netid else '')).execute()

        print(f"Added {name} to eboard")
        return response.data
    
    except Exception as e:
        pass
        # raise Exception(f"Error adding/updating points for {name}: {str(e)}")
    
    
# Get points via the responses object from Google Forms
# This is good to use when collecting responses from an event that copied the base template
def add_members(form_id: str, points_to_add: int, credentials=None, env: str = "production"):
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
                add_or_update_points(netid=netid, points_to_add=points_to_add, name=name, reason=reason, env=env)
            except KeyError as e:
                print(f"Error processing submission: {e}")
                continue

    except Exception as e:
        raise Exception(f"Error retrieving form responses: {str(e)}")
    else:
        print(f"Retrieved and processed {len(form_responses)} member responses")


def add_event(name: str = None, description: str = None, flyer_url: str = None, insta=None,
              month: str = None, day: str = None, year: str = None, env: str = "production"):
    try:
        sb = get_client(env)
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
            sb.table("events")
            .insert(event_data)
            .execute()
        )

        print(f"Added event: {name}")
        return response.data
    except Exception as e:
        raise Exception(f"Error adding event {name}: {str(e)}")