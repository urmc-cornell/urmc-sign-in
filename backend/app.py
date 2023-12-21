from flask import Flask
import os
import json
import view_model
import errors

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
    try:
        view_model.create_event(title=str(title), date=str(date), time=str(time))
    except errors.EventAlreadyExistsException:
        return json.dumps({"status": "400", "message": f"Event with title {title} already exists"})    
    except Exception as e:
        return json.dumps({"status": "500", "message": f"{e}"})   
    else:
        return json.dumps({"status": "200", "message": f"Successful Request - Created {title}"})   
    
# Add or Update Points for a specifc netid
@app.route('/points/<name>/<netid>/<points>', methods=["POST"])
def modify_points(name, netid, points):
    try:
        view_model.add_or_update_points(name=name, netid=netid, points_to_add=points)
    except:
        return json.dumps({"status": "500", "message": f"Internal Server Error :("})
    else:
        return json.dumps({"status": "200", "message": f"Successful Request"})  
    
# Get points from form via a google sheet. Need to have column with "NetID:" and a column with "Name:"
# Good for cases when the base form wasn't used to make the form
@app.route('/points/spreadsheet/<spreadsheet_id>/<points>', methods=["GET"])
def get_points_from_spreadhseet(spreadsheet_id, points):
    try:
        view_model.get_points_from_spreadsheet(spreadsheet_id=spreadsheet_id, points_to_add=points)
    except Exception as e:
        return json.dumps({"status": "500", "message": f"Internal Server Error :(. {e}"})
    else:
        return json.dumps({"status": "200", "message": "Successful Request"})
    
# Get points via the responses object from Google Forms
# This is good to use when collecting responses from an event that copied the base template
@app.route('/points/form/<form_id>/<points>', methods=["GET"])
def get_points_from_form_responses(form_id, points):
    try:
        view_model.retrieve_event_responses(form_id=form_id, points_to_add=points)
    except Exception as e:
        return json.dumps({"status": "500", "message": f"Internal Server Error :(. {e}"})
    else:
        return json.dumps({"status": "200", "message": "Successful Request"})

# Get top x number of people in terms of points
@app.route('/points/<number>', methods=["GET"])
def get_top_points(number):
    try:
        list_of_people = view_model.get_top_points(number=number)
    except Exception as e:
        return json.dumps({"status": "500", "message": f"Internal Server Error :(. {e}"})
    else:
        # return a json with the information and the status
        return list_of_people
    
# Get points for specifc netid
@app.route('/points/person/<netid>', methods=["GET"])
def get_netid_points(netid):
    try:
        points = view_model.get_netid_points(netid=netid)
    except Exception as e:
        return json.dumps({"status": "500", "message": f"Internal Server Error :(. {e}"})
    else:
        # return a json with the information and the status
        if points == "DNE":
            return json.dumps({"status": "404", "message": "NetID not found"})
        else:
            return json.dumps({"points":points})


# Run Server
if __name__ == '__main__':
    app.run(debug=True)