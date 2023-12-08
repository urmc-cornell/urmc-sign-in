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
        form_id = response['formId']
        print(form_id)

        # create_event_qr_code()
    except gspread.exceptions.APIError:
        raise errors.EventAlreadyExistsException
    except:
        raise Exception("There was an error")
    else:
        return "Created event sheet, form, and QR Code"
    
# Create the event form 
def create_event_form(title: str):
    url = 'https://forms.googleapis.com/v1/forms/'
    head = {'Authorization': 'Bearer {}'.format(creds.token)}
    to_send = {
        "info": {
            "title": f"{title}",
            "documentTitle": f"{title}",
        }
    } 
    response = requests.post(url=url, headers=head,json=to_send)
    return json.loads(response.text)
    


def update_form_info(formId: str):
    pass
        # "items": [
    #     {
    #         "itemId": "431bc60d",
    #         "title": "Name:",
    #         "questionItem": {
    #             "question": {
    #                 "questionId": "7650a8fe",
    #                 "required": "true",
    #                 "textQuestion": {}
    #             }
    #         }
    #     },
    #     {
    #         "itemId": "776b3683",
    #         "title": "NetID:",
    #         "questionItem": {
    #             "question": {
    #                 "questionId": "4059b2ed",
    #                 "required": "true",
    #                 "textQuestion": {}
    #             }
    #         }
    #     },
    #     {
    #         "itemId": "451a588b",
    #         "title": "Year:",
    #         "questionItem": {
    #             "question": {
    #                 "questionId": "02ab4ed9",
    #                 "required": "true",
    #                 "choiceQuestion": {
    #                     "type": "RADIO",
    #                     "options": [
    #                         {
    #                             "value": "Freshman"
    #                         },
    #                         {
    #                             "value": "Sophmore"
    #                         },
    #                         {
    #                             "value": "Junior"
    #                         },
    #                         {
    #                             "value": "Senior"
    #                         },
    #                         {
    #                             "isOther": "true"
    #                         }
    #                     ]
    #                 }
    #             }
    #         }
    #     },
    #     {
    #         "itemId": "3ef83fcc",
    #         "title": "Major:",
    #         "questionItem": {
    #             "question": {
    #                 "questionId": "4c00b23e",
    #                 "required": "true",
    #                 "choiceQuestion": {
    #                     "type": "CHECKBOX",
    #                     "options": [
    #                         {
    #                             "value": "CS"
    #                         },
    #                         {
    #                             "value": "ECE"
    #                         },
    #                         {
    #                             "value": "IS/ISST"
    #                         },
    #                         {
    #                             "value": "ORIE"
    #                         },
    #                         {
    #                             "isOther": "true"
    #                         }
    #                     ]
    #                 }
    #             }
    #         }
    #     },
    #     {
    #         "itemId": "631ebe43",
    #         "title": "Demographic:",
    #         "questionItem": {
    #             "question": {
    #                 "questionId": "3ba64dab",
    #                 "required": "true",
    #                 "choiceQuestion": {
    #                     "type": "RADIO",
    #                     "options": [
    #                         {
    #                             "value": "Male"
    #                         },
    #                         {
    #                             "value": "Female"
    #                         },
    #                         {
    #                             "value": "Non-Binary"
    #                         },
    #                         {
    #                             "isOther": "true"
    #                         }
    #                     ]
    #                 }
    #             }
    #         }
    #     },
    #     {
    #         "itemId": "04228741",
    #         "title": "Which URMC communication platform would you like to join?",
    #         "questionItem": {
    #             "question": {
    #                 "questionId": "43000701",
    #                 "required": "true",
    #                 "choiceQuestion": {
    #                     "type": "CHECKBOX",
    #                     "options": [
    #                         {
    #                             "value": "Listserv"
    #                         },
    #                         {
    #                             "value": "Google Calander"
    #                         },
    #                         {
    #                             "value": "Slack"
    #                         },
    #                         {
    #                             "value": "Already in all! :D"
    #                         }
    #                     ]
    #                 }
    #             }
    #         }
    #     },
    #     {
    #         "itemId": "5805f283",
    #         "title": "How did you hear about URMC?",
    #         "questionItem": {
    #             "question": {
    #                 "questionId": "140f52f1",
    #                 "required": "true",
    #                 "choiceQuestion": {
    #                     "type": "CHECKBOX",
    #                     "options": [
    #                         {
    #                             "value": "URMC website"
    #                         },
    #                         {
    #                             "value": "URMC Insta"
    #                         },
    #                         {
    #                             "value": "Friend/Peer"
    #                         },
    #                         {
    #                             "value": "Through Cornell (Ex. DPE, Class, AEW, etc)"
    #                         },
    #                         {
    #                             "isOther": "true"
    #                         }
    #                     ]
    #                 }
    #             }
    #         }
    #     },
    #     {
    #         "itemId": "01821cda",
    #         "title": "Any questions, comments, or concerns?",
    #         "questionItem": {
    #             "question": {
    #                 "questionId": "11f4baa5",
    #                 "textQuestion": {
    #                     "paragraph": "true"
    #                 }
    #             }
    #         }
    #     }
    # ]

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
