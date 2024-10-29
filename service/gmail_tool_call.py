import os
import re
import json
import datetime
import psycopg2
from psycopg2.extras import DictCursor
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain.tools import BaseTool
from langchain_anthropic import ChatAnthropic
from langchain.prompts import ChatPromptTemplate
from langchain.memory import ConversationBufferMemory
from langchain.schema import AgentAction, AgentFinish
from langchain.callbacks.manager import CallbackManagerForChainRun
from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain_core.prompts.chat import ChatPromptTemplate, MessagesPlaceholder

from utils.db import create_db_connection
from service.stripe import retrieve_customer_subscription_status
from service.agents.process_messages import process_gmail_conversations
from service.auth import decode_email_from_access_token, get_user_gmail_credentials, refresh_gmail_token, update_user_gmail_credentials
from service.gmail_tools.conversations.get_message import GmailTool

def generate_placeholder(category: str, index: int) -> str:
    return f"{category.upper()}_{index}"

def anonymize_data(text: str) -> Tuple[str, Dict[str, str]]:
    patterns = {
        'NAME': r'\b[A-Z][a-z]+ (?:[A-Z][a-z]+ )?[A-Z][a-z]+\b',
        'SSN': r'\b\d{3}-\d{2}-\d{4}\b',
        'EMAIL': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'PHONE': r'\b(\+\d{1,2}\s)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b',
        'CREDIT_CARD': r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
        'ADDRESS': r'\b\d+\s+([A-Za-z]+\s){1,3}(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd)\.?\b'
    }

    anonymized_data = {}
    category_counters = {category: 1 for category in patterns.keys()}

    def replace_match(match, category):
        original = match.group(0)
        if original not in anonymized_data:
            placeholder = generate_placeholder(category, category_counters[category])
            anonymized_data[original] = placeholder
            category_counters[category] += 1
        return anonymized_data[original]

    for category, pattern in patterns.items():
        text = re.sub(pattern, lambda m: replace_match(m, category), text)

    return text, anonymized_data

class AnonymizingAgentExecutor(AgentExecutor):
    anonymization_mapping: Dict[str, str] = {}

    @classmethod
    def from_agent_and_tools(cls, agent, tools, verbose=False, **kwargs):
        executor = super().from_agent_and_tools(agent, tools, verbose, **kwargs)
        executor.anonymization_mapping = {}
        executor.wrap_tools_with_anonymization()
        return executor
    
    def wrap_tools_with_anonymization(self):
        for tool in self.tools:
            original_run = tool.run
            def anonymizing_run(self, query: str, **kwargs) -> str:
                result = original_run(query, **kwargs)
                anonymized_result, mapping = anonymize_data(result)
                self.anonymization_mapping.update(mapping)
                return anonymized_result
            tool.run = anonymizing_run.__get__(tool, BaseTool)
    
    def de_anonymize(self, text: str) -> str:
        reverse_mapping = {v: k for k, v in self.anonymization_mapping.items()}
        
        sorted_keys = sorted(reverse_mapping.keys(), key=len, reverse=True)
        
        for key in sorted_keys:
            text = text.replace(key, reverse_mapping[key])
        
        return text

    def invoke(
        self,
        input: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        input_text = input.get("input", "")
        
        anonymized_input, mapping = anonymize_data(input_text)
        self.anonymization_mapping.update(mapping)
        
        anonymized_input_dict = {**input, "input": anonymized_input}
        
        anonymized_result = super().invoke(anonymized_input_dict, config, **kwargs)
        
        result = self.de_anonymize(anonymized_result["output"])
        
        return {"output": result}

def get_current_date():
    return datetime.datetime.now().date()

current_date = datetime.datetime.now().date().strftime('%Y-%m-%d')  

def run_gmail_conversation(access_token, new_message, email, timezone, chat_history):
    conn = create_db_connection()
    user_gmail_credentials = get_user_gmail_credentials(conn, email)
    print("user_gmail_credentials:::", user_gmail_credentials)

    add_usage_to_db(conn, email)
    subscription_status, subscription_usage = retrieve_customer_subscription_status(email)
    if subscription_status != 'active' and subscription_usage >= 1000:
        return "You have reached the usage limit for today. Please subscribe to continue.", 1000

    subscription_usage = 0
    credentials = user_gmail_credentials.get('credentials')
    if not credentials:
        return "Credentials are None", 0
    
    credentials = json.loads(credentials) if isinstance(credentials, str) else credentials
    refresh_token = credentials.get('refresh_token')
    if not refresh_token:
        return "Refresh token is None", 0
    
    new_credentials = refresh_gmail_token(refresh_token)
    email, access_token = decode_email_from_access_token(new_credentials.get('access_token'))

    tools = [
        # process_gmail_conversations(access_token, new_message, email, timezone, chat_history)
    ]

    root = os.path.abspath(os.path.dirname(__file__))
    system_prompt_path = os.path.join(root, "system_prompt.txt")
    with open(system_prompt_path, "r") as f:
        system = f.read()
    
    human = '''{input}
        {agent_scratchpad}
        (reminder to respond in a JSON blob no matter what)'''
    human += f"Current date: {current_date} and timezone is {timezone}"
    
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", human),
        ]
    )

    llm = ChatAnthropic(model='claude-3-5-sonnet-20240620', api_key=os.getenv("PROD_CLAUDE_API_KEY"), temperature=0, max_tokens=500)

    agent = create_structured_chat_agent(llm, tools, prompt)
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

    history = memory.chat_memory.messages
    if chat_history:
        last_role = None
        first_message = True
        for message in chat_history:
            updated_message = {}
            current_role = 'user' if message.get('sender') == 'user' else 'ai'
            
            if current_role == last_role:
                continue  
            
            content = str(message.get('text', '')).trim()
            if not content:  
                continue
            
            if first_message and current_role == 'ai':
                first_message = False
                continue  
            
            updated_message['role'] = current_role
            updated_message['content'] = content
            history.append(updated_message)
            last_role = current_role
            first_message = False

    agent_executor = AnonymizingAgentExecutor(agent=agent, 
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
                        "input": new_message,
                        "chat_history": []
                            })
                break  
            except Exception as e:
                retry_count += 1
                if retry_count == max_retries:
                    raise  
                print("error:::", e)
            print(f"Attempt {retry_count} failed. Retrying...")
    except Exception as e:
        print("An error occurred while executing the agent gmail tool call:", e)
        return "Unable to answer the question. Please try again!!", 0
    
    if not isinstance(result, dict):
        try:
            pattern = r"(\w+):\s*([^,]+)(?:,|$)"
            args = dict(re.findall(pattern, result))
            if args.get('Error') and len(args.get('Error')) > 0:
                print("Agent:", args.get('Error'))
            else: 
                pattern = r'"result":\s*"(.*?)"'
                match = re.search(pattern, result)
                message = match.group(1)
                print("Agent:", message)
        except Exception as e:
            print("An error occurred while parsing the output:", e)
            try:
                error_message = str(e)
                start = error_message.find('{')
                end = error_message.find('}') + 1
                result_json = json.loads(error_message[start:end])
                result_value = result_json['result']
                print("Result value:", result_value)
            except (ValueError, KeyError):
                print("Error:", error_message)
            return error_message, 0
    else:
        
        return result.get('output') if result.get('output') else "Unable to answer the question", subscription_usage


def ask_gmail_api(access_token, message, email, timezone, chat_history):  
    if isinstance(message, dict):
        message = str(message.get('text', ''))
    elif not isinstance(message, str):
        message = str(message)
    
    if not access_token or not email:
        print("Error: access_token or email is missing")
        return "Unable to process the request due to missing credentials.", 0
    
    try:
        result, usage = run_gmail_conversation(access_token, message, email, timezone, chat_history)
        return str(result), usage
    except Exception as e:
        print(f"An error occurred while executing the agent gmail tool call: {e}")
        return "Unable to answer the question. Please try again!!", 0


def add_usage_to_db(conn, email):
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("UPDATE \"user_gmail_credentials\" SET usage = usage + %s, \"update_date\" = NOW() WHERE email = %s", (1, email))
            conn.commit()
        return True
    except psycopg2.Error as e:
        print(f"Error updating user gmail credentials: {e}")
        conn.rollback()
        return False, None

