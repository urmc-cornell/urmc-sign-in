import gspread

# GSpread Info
sa = gspread.service_account(filename="service_account.json")

sh = sa.open("URMC-Point-Tracking-SP24")

wks = sh.worksheet("Points")