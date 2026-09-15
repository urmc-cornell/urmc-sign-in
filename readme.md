## Installation & Setup

1. **Clone the repository** (if not already done):

   ```bash
   git clone <repository-url>
   cd urmc-sign-in
   ```

2. **Create and activate a virtual environment**:

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install required packages**:

   ```bash
   pip install -r requirements.txt
   ```

4. **Set up Google API credentials**:
   - Place your `client_secrets.json` file in the project root
   - This file should contain your Google OAuth 2.0 credentials

5. **Configure Environment Variables**:
   - Copy `.env.example` to `.env` in the project root and fill in the values
   - Ask a team member for the actual credentials

## Running the Application

1. **Run the Flask application**:

   ```bash
   python web/app.py
   ```

2. **Access the application** at `http://localhost:8080`
   - You'll be redirected to Google OAuth for authentication

## Update selected members from a Google Sheet

In the existing dashboard, open **Import Members → Google Sheet**:

1. Paste the sheet link and click **Load Sheet**. The first tab loads by default;
   choose another tab and load again if needed.
2. Map the email column to `netid` (email before `@cornell.edu`) and map any profile
   columns you want to update. Use **Full name → first_name + last_name** for a Name
   column. Leave other headers on **Ignore**.
3. Click **Show People**, check specific responses or **Select everyone**, then
   click **Update Selected People**. The button names the target environment.

Only selected people's mapped, nonblank fields are written. Existing IDs, points,
events, and unmapped values are preserved. New members need a mapped name and are
not automatically assigned eboard status. Headshot columns accept Drive file links
and reuse the existing uploader, only for selected people. Each row shows its result.
Headshots upload to unique filenames in Supabase Storage before their URLs are saved.
Previous images remain in storage so failed replacements cannot break existing photos;
unused images are not automatically cleaned up.
For duplicate NetIDs, select one response; Select everyone uses the last sheet row.
Loaded sheets expire after an hour or a server restart. No new database or website
changes are needed. Use the dashboard's Production environment for direct live updates;
the existing full staging push is not required for these selective updates.

Run the offline checks with `venv/bin/python -m unittest discover -s tests -v`.
