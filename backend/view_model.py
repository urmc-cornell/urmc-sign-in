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
        new_event = models.Event(title=title, time=time, date=date, form_id=form_id, worksheet_id=worksheet_id,form_link=form_link) 

    except gspread.exceptions.APIError:
        raise errors.EventAlreadyExistsException
    except Exception as e:
        raise Exception(f"There was an error calling the create event functions: {e}")
    else:
        return new_event.serialize()
    
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
        
        # return list_of_people[:int(number)]
        list_of_people_cutoff = list_of_people[:int(number)]
        position = 0
        for person in list_of_people_cutoff:
            position += 1
            print(f"{position}. {person['name']} ({person['netid']}) : {person['points']}")

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


# Get points from a Google Spreadsheet
# Good to use if a form was made that did not copy the base template
def get_points_from_spreadsheet(spreadsheet_id: str, points_to_add: int):
    spreadsheet = sa.open_by_key(str(spreadsheet_id))
    worksheet = spreadsheet.worksheet("Form Responses 1")
    people = []
    try:
        find_netid_column = worksheet.find("NetID:")
        find_name_column = worksheet.find("Name:")
    except:
        raise Exception("Error getting name or netid from spreadsheet")
    else:
        netid_column = find_netid_column.col
        name_column = find_name_column.col
        netid_list = worksheet.col_values(netid_column)
        name_list = worksheet.col_values(name_column)

        # add people as a tuple (netid, name) to people list
        # need to start at index 1 to avoid adding ("NetID:", "Name:") to spreadsheet
        for index in range(1, len(name_list)):
            people.append((netid_list[index], name_list[index]))
            print(netid_list[index])

        # Update person's points for attending the event
        for person in people:
            add_or_update_points(name=person[1], netid=person[0], points_to_add=points_to_add)
        
        print(f"Updated points for {len(people)} people")

# Get points via the responses object from Google Forms
# This is good to use when collecting responses from an event that copied the base template
def retrieve_event_responses(form_id: str, points_to_add: int):
    try:
        url = f"https://forms.googleapis.com/v1/forms/{form_id}/responses"
        head = {'Authorization': 'Bearer {}'.format(creds.token)}
        request = requests.get(url=url, headers=head)
        response = json.loads(request.text)
        form_responses = response['responses']
        
        # check that this works from other form responses as well
        # test on forms that were not copied from base event
        for submission in form_responses:
            submission_info = submission['answers']
            name = submission_info["7650a8fe"]['textAnswers']['answers'][0]['value']
            netid = submission_info["4059b2ed"]['textAnswers']['answers'][0]['value']
            add_or_update_points(name, netid, points_to_add)

    except Exception as e:
        raise Exception(f"{e}")
    else:
        print("Retrieved event responses")