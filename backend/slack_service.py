from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import os
from dotenv import load_dotenv
import ssl

# Load environment variables
load_dotenv()

# Create a custom SSL context that doesn't verify certificates
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Initialize Slack client with SSL context
slack_client = WebClient(
    token=os.getenv('SLACK_BOT_TOKEN'),
    ssl=ssl_context  # Add this parameter
)

def send_points_notification(email: str, points: int, reason: str):
    """
    Send a Slack notification to a user about points they received
    
    Args:
        email (str): The user's email address (used to look up Slack user)
        points (int): Number of points received
        reason (str): Reason for receiving points
    """
    try:
        # Look up user by email
        result = slack_client.users_lookupByEmail(email=email)
        user_id = result["user"]["id"]
        
        # Construct message with proper singular/plural form
        point_text = "point" if points == 1 else "points"
        message = f"🎉 You've earned *{points} {point_text}* for: {reason}"
        
        # Send DM to user
        slack_client.chat_postMessage(
            channel=user_id,
            text=message
        )
        
    except SlackApiError as e:
        print(f"Error sending Slack notification: {str(e)}") 