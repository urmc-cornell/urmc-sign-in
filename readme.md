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
   - Place your `client_secrets.json` file in the `web/` directory
   - This file should contain your Google OAuth 2.0 credentials

## Running the Application

1. **Navigate to the web directory**:

   ```bash
   cd web
   ```

2. **Run the Flask application**:

   ```bash
   python3 app.py
   ```

3. **Access the application**:
   - Open your web browser and go to `http://localhost:8080`
   - You'll be redirected to Google OAuth for authentication
