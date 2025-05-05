# URMC Sign-In System

## Setup

1. Clone this repository
2. Install the requirements:
   ```
   pip install -r requirements.txt
   ```
3. Add secret files

- Add env files to backend and web directories
- Add client_secrets.json to web directory

## Running the Application

To start the web application:

1. Navigate to the project root directory
2. Run the Flask application:
   ```
   cd web
   python app.py
   ```
3. Open your browser and go to `http://localhost:8080`
4. Log in with your Google account that has access to the forms

## Features

- Google Forms integration to track event attendance
- E-board and TA form response processing

## Application Structure

- `web/` - Contains the Flask web application
  - `app.py` - Main Flask application
  - `dashboard.html` - Dashboard UI
  - `client_secrets.json` - Google OAuth credentials
- `backend/` - Backend services
  - `point_service.py` - Service for managing member points
  - Other support modules for the application logic
