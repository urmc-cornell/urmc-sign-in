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
            print(f"new value is {new_value}")
            points_sheet.update(f'C{position}', int(new_value))
            print(f"Updated {name}: {curr_value} -> {new_value} points")
