from flask import Flask
import os
import json
import gspread


# Initialise Flask App
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

def create_app():
    app = Flask(__name__)
    app.config.from_object("project.config")
    return app

# Create Event
@app.route('/create/<title>/<date>/<time>', methods=["POST"])
def create_event(title, date, time):
    # add a new sheet in the spreadsheet with the title
    # A1 is set to "Attendees"
    #B1 is "info"
    # B2 Date
    # B3 Time
    return "hello"


# Run Server
if __name__ == '__main__':
    app.run(debug=True)