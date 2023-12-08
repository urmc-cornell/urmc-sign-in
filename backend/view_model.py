import gspread
import errors
import json
import requests
import creds

# GSpread Info
sa = gspread.service_account(filename="service_account.json")
sh = sa.open("URMC-Point-Tracking-SP24")
points_sheet = sh.worksheet("Points")

# Function that holds sub tasks
def create_event(title: str, time:str, date:str):
    try:
        create_event_sheet(title=title, time=time, date=date)
        response = create_event_form(title=title)
        print(response)
        form_id = response["id"]
        print(form_id)
        update_form_info(form_id=form_id, title=title)

        # create_event_qr_code()
    except gspread.exceptions.APIError:
        raise errors.EventAlreadyExistsException
    except:
        raise Exception("There was an error")
    else:
        return "Created event sheet, form, and QR Code"
    
# Create the event form 
# Copying base form file
def create_event_form(title: str):
    form_id = "14I6DQ8Ccw2miqUz8_m1_qUsMH3R7vO4vBVVNHo14Enc"
    url = f'https://www.googleapis.com/drive/v3/files/{form_id}/copy'
    head = {'Authorization': 'Bearer {}'.format(creds.token)}
    to_send = {
        "info": {
            "title": f"{title}",
        }
    } 
    response = requests.post(url=url, headers=head,json=to_send)
    return json.loads(response.text)
    

def update_form_info(form_id: str, title:str):
    url = f'https://forms.googleapis.com/v1/forms/{form_id}:batchUpdate'
    head = {'Authorization': 'Bearer {}'.format(creds.token)}

    # Need to use Google Drive API to update the file name
    to_send =  {
        "requests": [
            {
        "updateFormInfo": {
            "info": {
                "description": "Please sign in to mark your attendance :).",
                "title": f"{title}",
            },
            "updateMask": "description, title"
        }
    }
    ]
 }

    try:
        # requests.post(url=url, headers=head,json=to_send)
        requests.post(url=url, headers=head,json=to_send)
    except:
        raise Exception("Could not update form")
    else:
        print("Updated form")

# Get the responses from the form at a form_id
# Update corresponding attendance sheet
# Update points sheet
def retrieve_event_responses(form_id: str):
    pass

# create the event qr code
def create_event_qr_code():
    pass

# Create the event sheet and add metadata
def create_event_sheet(title: str, time:str, date:str):
    try:
        event_worksheet = sh.add_worksheet(title=title, rows=100, cols=8)
        event_worksheet.update('A1', "Attendees")
        event_worksheet.update('B1', f"Date: {date}")
        event_worksheet.update('C1', f"Time: {time}")
    except gspread.exceptions.APIError:
        raise errors.EventAlreadyExistsException
    except:
        raise Exception("There was an error")
    else:
        return True

def add_or_update_points(name: str, netid: str, points_to_add: int):
    # MARK: Updating Points Section
    # Try to find netid in sheet
    try:
        position = points_sheet.find(netid).row

    # User DNE in Sheet
    except:
        points_sheet.append_row([name, netid, int(points_to_add)])
        print(f"Added {name} with {points_to_add} points to spreadsheet")

    # User exists in sheet
    else:
        if position != None:
            # Add points to add to users current points
            curr_value = points_sheet.acell(f'C{position}').value 
            new_value = int(curr_value) + int(points_to_add)
            # Update points cel to be this new value
            points_sheet.update(f'C{position}', int(new_value))
            print(f"Updated {name}: {curr_value} -> {new_value} points")
