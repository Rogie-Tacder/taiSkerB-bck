import json
import base64 
import requests
from langchain.tools import BaseTool
from typing import Union, ClassVar, Optional
from pydantic import Field

class GmailTool(BaseTool):
    name: ClassVar[str] = "GmailTool"
    description: ClassVar[str] = "A tool for interacting with Gmail"

    access_token: Optional[str] = Field(None, description="The access token for Gmail API")
    email: Optional[str] = Field(None, description="The email address of the user")
    timezone: Optional[str] = Field(None, description="The timezone of the user")

    def _run(self, action: str, **kwargs) -> str:
        if action == "send_email":
            return self.send_email(**kwargs)
        elif action == "read_email":
            return self.read_email(**kwargs)
        else:
            return f"Unknown action: {action}"

    def send_email(self, **kwargs) -> str:
        if not self.access_token:
            return "Access token not set. Please initialize credentials first."
        
        recipient = kwargs.get('recipient')
        subject = kwargs.get('subject')
        body = kwargs.get('body')
        
        if not all([recipient, subject, body]):
            return "Missing required parameters: recipient, subject, or body"
        
        url = "https://www.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        message = f"To: {recipient}\r\nSubject: {subject}\r\n\r\n{body}"
        raw_message = base64.urlsafe_b64encode(message.encode()).decode()
        payload = {
            'raw': raw_message
        }
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            return f"Email sent to {recipient} with subject '{subject}'."
        else:
            return f"Failed to send email to {recipient} with subject '{subject}'. Status code: {response.status_code}"

    def read_email(self, email_id: str) -> str:
        if not self.access_token or not self.email:
            return "Access token or email not set. Please initialize credentials first."
        url = f"https://www.googleapis.com/gmail/v1/users/{self.email}/messages/{email_id}"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            email_data = response.json()
            return self._parse_email_content(email_data)
        else:
            return f"Failed to read email with ID: {email_id}. Status code: {response.status_code}"

    def _parse_email_content(self, email_data: dict) -> str:
        parts = email_data.get('payload', {}).get('parts', [])
        if not parts:
            return email_data.get('snippet', 'No content found')

        for part in parts:
            if part.get('mimeType') == 'text/plain':
                body = part.get('body', {}).get('data', '')
                if body:
                    return base64.urlsafe_b64decode(body).decode('utf-8')

        return 'No plain text content found'
