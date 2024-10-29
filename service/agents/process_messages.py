import datetime
import os
import re
import json
from langchain.prompts import ChatPromptTemplate
from langchain.memory import ConversationBufferMemory
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from typing import Dict, List

from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain.memory import ConversationBufferMemory
from langchain_core.prompts.chat import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from utils.db import create_db_connection
from service.auth import decode_email_from_access_token, get_user_gmail_credentials, refresh_gmail_token
from service.gmail_tools.conversations.get_message import GmailTool


# Add this near the top of your script, after the imports
def get_current_date():
    return datetime.datetime.now().date()

current_date = datetime.datetime.now().date().strftime('%Y-%m-%d')  # Format as 'YYYY-MM-DD'

def run_gmail_conversation(access_token, new_message, email, timezone, chat_history):
    conn = create_db_connection()
    user_gmail_credentials = get_user_gmail_credentials(conn, email)
    credentials = user_gmail_credentials.get('credentials')
    print(credentials)
    if not credentials:
        return "Credentials are None"
    
    credentials = json.loads(credentials) if isinstance(credentials, str) else credentials
    refresh_token = credentials.get('refresh_token')
    if not refresh_token:
        return "Refresh token is None3"
    
    new_credentials = refresh_gmail_token(refresh_token)
    email, access_token = decode_email_from_access_token(new_credentials.get('access_token'))

    # Define tools here
    tools = [
        GmailTool(access_token)

    ]

    # Optimize token usage by moving system prompt to a separate file
    root = os.path.abspath(os.path.dirname(__file__))
    system_prompt_path = os.path.join(root, "conversations_system_prompt.txt")
    with open(system_prompt_path, "r") as f:
        system = f.read()
    
    human = '''{input}

            {agent_scratchpad}

            (reminder to respond in a JSON blob no matter what)'''
    # timezone = "Europe/London" if not timezone else timezone
    human += f"Current date: {current_date} and timezone is {timezone}"
    
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", human),
        ]
    )

    llm = ChatOpenAI(model='gpt-4o-mini', openai_api_key=os.getenv("PROD_OPENAI_API_KEY"), temperature=0, max_tokens=500)

    agent = create_structured_chat_agent(llm, tools, prompt)
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

    history = memory.chat_memory.messages
    if chat_history:
        for message in chat_history:
            updated_message = {}
            updated_message['role'] = message.get('sender') if message.get('sender') == 'user' else 'ai'
            updated_message['content'] = str(message.get('text'))
            history.append(updated_message)
            print(updated_message)

    agent_executor = AgentExecutor(agent=agent, 
                                   tools=tools, 
                                   memory=memory, 
                                   max_iterations=10, 
                                   handle_parsing_errors=True,
                                   remember_intermediate_steps=True,
                                   verbose=True)
    

    max_retries = 3
    retry_count = 0
    try:    
        while retry_count < max_retries:
            try:
                result = agent_executor.invoke({
                        "input": str(new_message),
                        "chat_history": []
                            })
                break  # If successful, exit the loop
            except Exception as e:
                retry_count += 1
                if retry_count == max_retries:
                    raise  # Re-raise the last exception if all retries are exhausted
                print(f"Attempt {retry_count} failed. Retrying...")
    except Exception as e:
        print("An error occurred while executing the agent gmail tool call:", e)
        return "Unable to answer the question. Please try again!!"
    
    if not isinstance(result, dict):
        try:
            # Attempt to parse the result as JSON if it's a string
            if isinstance(result, str):
                print("Result is a string, attempting to parse:", result)  # Debugging line
                result = json.loads(result)  # Parse the string to a dictionary
            
            # Check if result is now a dictionary
            if isinstance(result, dict):
                if result.get('Error') and len(result.get('Error')) > 0:
                    print("Agent:", result.get('Error'))
                else: 
                    pattern = r'"result":\s*"(.*?)"'
                    match = re.search(pattern, json.dumps(result))  # Ensure we search in a string
                    if match:
                        message = match.group(1)
                        print("Agent:", message)
                    else:
                        print("No message found in the result.")
            else:
                print("Result is not a dictionary after parsing:", result)  # Debugging line
        except json.JSONDecodeError as json_err:
            print("JSON decoding error:", json_err)
        except Exception as e:
            # Handle the case where the output cannot be parsed
            print("An error occurred while parsing the output:", e)
            try:
                # Try to extract the result from the error message
                error_message = str(e)
                start = error_message.find('{')
                end = error_message.find('}') + 1
                result_json = json.loads(error_message[start:end])
                result_value = result_json['result']
                print("Result value:", result_value)
            except (ValueError, KeyError):
                # If the result value cannot be extracted, print the original error message
                print("Error:", error_message)
            return error_message
    else:
        
        return result.get('output') if result.get('output') else "Unable to answer the question"


class GmailWorkflowsInput(BaseModel):
    new_message: Dict[str, str]

def process_gmail_conversations(access_token, new_message, email, timezone, chat_history):
    def process_conversations(input_data: GmailWorkflowsInput) -> str:
        """
        Fetches details on conversations, threads, messages, etc from Gmail

        Args:
        - input_data (GmailWorkflowsInput): Contains the new_message to process

        Returns:
        - str: JSON response from the Gmail API
        """
        new_message_str = json.dumps(input_data.new_message)
        return run_gmail_conversation(access_token, new_message_str, email, timezone, chat_history)
    
    return StructuredTool.from_function(
        func=process_conversations,
        name="process_gmail_conversations",   
        description="Fetch and analyze Gmail conversations details like conversations, threads, messages, etc",
        args_schema=GmailWorkflowsInput
    )
