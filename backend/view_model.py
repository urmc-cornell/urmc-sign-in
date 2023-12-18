import gspread
import json
import requests
# Custom Modules
import errors
import creds
import models

# GSpread Info
sa = gspread.service_account(filename="service_account.json")
sh = sa.open("URMC-Point-Tracking-SP24")
points_sheet = sh.worksheet("Points")

# Function that holds sub tasks
def create_event(title: str, time:str, date:str):
    try:
        event_response = create_event_sheet(title=title, time=time, date=date)
        worksheet_id = event_response.id
        response = create_event_form(title=title)
        form_id = response["id"]
        update_form_info(form_id=form_id, title=title)
        update_form_title(form_id=form_id, title=title)
        form_link = get_form_link(form_id=form_id)
        # create_event_qr_code(form_link=form_link)
        title = models.Event(title=title, time=time, date=date, form_id=form_id, worksheet_id=worksheet_id,form_link=form_link) 
        models.events.add(title)
        print(models.events)

    except gspread.exceptions.APIError:
        raise errors.EventAlreadyExistsException
    except:
        raise Exception("There was an error calling the create event functions")
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
    try:
        response = requests.post(url=url, headers=head,json=to_send)
    except:
        raise Exception("There was an error creating the event form")
    else:
        print("Copied base event form")
        return json.loads(response.text)
    
def update_form_title(form_id:str, title:str):
    url = f'https://www.googleapis.com/drive/v3/files/{form_id}'
    head = {'Authorization': 'Bearer {}'.format(creds.token)}

    to_send = {"name":f"{title}"}

    try:
        requests.patch(url=url, headers=head,json=to_send)
    except:
        raise Exception("Could not update form Google Drive title")
    else:
        print("Updated form Google Drive Title")
    
def update_form_info(form_id: str, title:str):
    url = f'https://forms.googleapis.com/v1/forms/{form_id}:batchUpdate'
    head = {'Authorization': 'Bearer {}'.format(creds.token)}

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
        response = requests.post(url=url, headers=head,json=to_send)
    except:
        raise Exception("Could not update form description and title")
    else:
        print("Updated form title")
        return json.loads(response.text)

def get_form_link(form_id: str):
    try:
        url = f"https://forms.googleapis.com/v1/forms/{form_id}"
        head = {'Authorization': 'Bearer {}'.format(creds.token)}
        request = requests.get(url=url, headers=head)
        response = json.loads(request.text)
        link_to_form = response['responderUri']
    except:
        raise Exception("There was an error getting the form link")
    else:    
        return link_to_form

# create the event qr code
def create_event_qr_code(form_link:str):
    qr_code_request_link = f"https://api.qrserver.com/v1/create-qr-code/?data={form_link}&size=150x150"
    qr_request = requests.get(qr_code_request_link)
    # print(type(qr_request.raw))
    # print(type(qr_request.text))
    return qr_request

# Create the event sheet and add metadata
def create_event_sheet(title: str, time:str, date:str):
    try:
        response = event_worksheet = sh.add_worksheet(title=title, rows=100, cols=8)
        event_worksheet.update('A1', "Attendees")
        event_worksheet.update('B1', f"Date: {date}")
        event_worksheet.update('C1', f"Time: {time}")
    except gspread.exceptions.APIError:
        raise errors.EventAlreadyExistsException
    except:
        raise Exception("There was an error")
    else:
        return response
    
def retrieve_event_responses(form_id: str, sheet_id: int):
    try:
        url = f"https://forms.googleapis.com/v1/forms/{form_id}/responses"
        head = {'Authorization': 'Bearer {}'.format(creds.token)}
        request = requests.get(url=url, headers=head)
        response = json.loads(request.text)
        form_responses = response['responses']
        print(form_responses)
        
        # for submission in form_responses:
             # add_or_update_points(name, netid, 1)
                    
             # Update corresponding attendance sheet
                 # have to figure out how imma do this tbh

    except:
        raise Exception("Error trying to get event responses")
    else:
        print("Retrieved event responses")

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


def get_top_points(number: int):
    # get all values, then sort by points
    # assert type(number) == int
    try:
        point_info = points_sheet.get_all_records()
    except Exception as e:
        raise Exception(f"Could not get top {number} due to {e}")
    else:
        list_of_people = []
        for entry in point_info:
            if entry['Netid'] != '':
                list_of_people.append({"name": f"{entry['Name']}","netid": f"{entry['Netid']}","points": f"{entry['Points']}"})

        list_of_people.sort(key=lambda x: x['points'], reverse=True)

        if int(number) > len(list_of_people):
            number = len(list_of_people)
        
        return list_of_people[:int(number)]

def get_netid_points(netid: str):
    try:
        position = points_sheet.find(netid).row
    # User DNE in Sheet
    except:
        return "DNE"
    # User exists in sheet
    else:
        if position != None:
            curr_value = points_sheet.acell(f'C{position}').value 
            return curr_value

def get_points_from_spreadsheet(link_to_sheet: str, points_to_add: int):
    worksheet = sa.open_by_url(link_to_sheet)

    people = []
    # find col with netid text
        # get all the values in this col
    # find col with name text
        # get all vals in this col
    # add people as a tuple (netid, name) to people list

    # Update person's points for attending the event
    add_or_update_points(name=name, netid=netid, points_to_add=1)



