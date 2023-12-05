import gspread

# GSpread Info
sa = gspread.service_account(filename="service_account.json")
sh = sa.open("URMC-Point-Tracking-SP24")
points_sheet = sh.worksheet("Points")


def create_event(title: str, time:str, date:str):
    event_worksheet = sh.add_worksheet(title=title, rows=100, cols=8)
    event_worksheet.update('A1', "Attendees")
    event_worksheet.update('B1', f"Date: {date}")
    event_worksheet.update('C1', f"Time: {time}")

def sign_in(name: str, netid: str, points_to_add: int):

    # MARK: Updating Points Section

    # Try to find netid in sheet
    try:
        position = points_sheet.find(netid).row

    # User DNE in Sheet
    except:
        # TODO: binary search for next empty cell to add next person
        # add_location = 
        points_sheet.update(f'A{add_location}', name)
        points_sheet.update(f'B{add_location}', netid)
        points_sheet.update(f'C{add_location}', points_to_add)
        print("New Attendee Added")

    # Person in sheet
    else:
        # User exists in sheet
        if position != None:
            # Add points to add to users current points
            curr_value = points_sheet.acell(f'C{position}').value 
            new_value = int(curr_value) + points_to_add
            # Update points cel to be this new value
            points_sheet.update(f'C{position}', new_value)
            print(f"Updated")


    # MARK: Event Sign In
    # TODO: Implement updating corresponding event attendees list