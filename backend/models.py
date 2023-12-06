class User:
    def __init__(self, name: str, netid: str, points: int):
        self.name = name
        self.netid = netid
        self.points = points
    
    def __str__(self):
        return f"{self.name}({self.netid}): {self.points} points"

class Event:
    def __init__(self, title: str, time: str, date: str, attendees: list):
        self.title = title
        self.date = date
        self.time = time
        self.attendees = attendees
    
    def __str__(self):
        return f"{self.title} on {self.date} @ {self.time}"
    
    def get_attendees(self):
        return self.attendees