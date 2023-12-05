import gspread

# GSpread Info
sa = gspread.service_account(filename="service_account.json")

sh = sa.open("URMC-Point-Tracking-SP24")

wks = sh.worksheet("Points")


def create_event(title: str, time:str, date:str):
    event_worksheet = sh.add_worksheet(title=title, rows=100, cols=8)
    event_worksheet.update('A1', "Attendees")
    event_worksheet.update('B1', f"Date: {date}")
    event_worksheet.update('C1', f"Time: {time}")
