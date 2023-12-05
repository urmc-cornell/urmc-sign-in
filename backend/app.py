from flask import Flask
import os
import json


# Initialise Flask App
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

def create_app():
    app = Flask(__name__)
    app.config.from_object("project.config")
    return app

# Example 
@app.route('/', methods=["GET"])
def get():
    return "hello world"

# Run Server
if __name__ == '__main__':
    app.run(debug=True)