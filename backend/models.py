from typing import Any
import json


class User:
    def __init__(self, name: str, netid: str, points: int):
        self.name = name
        self.netid = netid
        self.points = points
    
    def __repr__(self):
        to_return = {
            "name": f"{self.name}",
            "netid": f"{self.netid}",
            "points": f"{self.points}"
        }
        return f"{to_return}"

    def __str__(self):
        to_return = {
            "name": f"{self.name}",
            "netid": f"{self.netid}",
            "points": f"{self.points}"
        }
        return to_return
    
    def toJson(self):
        return json.dumps(self, default=lambda o: o.__dict__)
    
    def __getitem__(self, item):
        list_of_vals = [self.name, self.netid, self.points]
        return list_of_vals[item]

class Event:
    def __init__(self, title: str, time: str, date: str, form_id: str, worksheet_id: int, form_link:str):
        self.title = title
        self.date = date
        self.time = time
        self.form_id = form_id
        self.worksheet_id = worksheet_id
        self.form_link = form_link
    
    def __repr__(self):
        return f"link to form: {self.form_link} : worksheet_id: {self.worksheet_id} : form_id: {self.form_id} "
    
    def __str__(self):
        to_return = {
            "title": f"{self.title}",
            "date": f"{self.date}",
            "time": f"{self.time}",
            "title": f"{self.title}",
            "form_id": f"{self.form_id}",
            "link_to_form": f"{self.form_link}",
            "worksheet_id": f"{self.worksheet_id}"
        }
        return to_return

events = set()