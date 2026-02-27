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
