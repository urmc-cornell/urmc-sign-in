from flask import Flask
import os
import json
import view_model


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
    except:
        raise Exception("Could not make request")
    else:
        return json.dumps({"status": "200", "message": f"Successful Request - Created {title}"})   

# Run Server
if __name__ == '__main__':
    app.run(debug=True)