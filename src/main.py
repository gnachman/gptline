#!/usr/bin/env python3
from dataclasses import dataclass
from src.background_task import BackgroundTask
from src.chat import create_chat, create_chat_with_spinner, suggest_name, invoke
from src.db import ChatDB
from src.formatting import print_message
from src.formatting import setMark
from src.highlight import SyntaxHighlighter
from src.input_reader import Chat, read_input, usage
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import HTML
from src.search import display_chat_search_results, display_search_results
from src.spin import Spinner
from src.ui_utils import draw_horizontal_line, draw_light_horizontal_line
import html
import json
from newspaper import Article
import openai
import os
import subprocess
import sys
import tiktoken
import traceback
from typing import Optional, Any, Callable
import requests
from html2text import html2text

openai.api_key = os.environ.get("OPENAI_API_KEY")
if not openai.api_key:
    openai.api_key = os.environ.get("OPENAI_KEY")
if not openai.api_key:
    print("Set the environment variable OPENAI_KEY or OPENAI_API_KEY to your api secret key")
    exit(1)

@dataclass
class Setting:
    name: str
    key: str
    # Take a decoded value and save it into App
    load: Callable
    default: Any
    # Returns a decoded value
    value: Callable
    # Take a string from the user and return a value that can be json encoded for storage. Throw if the value is bad.
    decode: Callable

def str_to_bool(s):
    if s.lower() == "y" or s.lower() == "t" or s.lower() == "true":
      return True
    if s.lower() == "n" or s.lower() == "f" or s.lower() == "false":
      return False
    raise Exception("Boolean values must be 'true' or 'false'")

class App:
    def __init__(self):
        self.tasks = []
        self.chat_db = ChatDB()
        self.current_chat_id = None
        self.messages = []
        self.placeholder = ""
        self.allow_execution = False
        self.temperature = 0
        self.chats = []
        self.chat = None
        self.content = None
        self.max_tokens = 8000
        self.load_settings()
        self.print_settings()
        self.index_all_chats()

    def new_chat(self):
        self.current_chat_id = self.chat_db.create_chat("New chat")
        self.messages.clear()
        self.messages.append({
            "role": "system",
            "content": "You assist a user in a terminal emulator."})
        self.chat_db.add_message(self.current_chat_id, self.messages[0]["role"],
                self.messages[0]["content"], None, None)
        return self.current_chat_id

    def run_forever(self):
        while True:
            self.iterate()

    def delete_until_user_message(self):
         while self.messages[-1]["role"] == "assistant" or self.messages[-1]["role"] == "function" or "function_call" in self.messages[-1]:
             self.chat_db.delete_message(self.messages[-1]["id"])
             self.messages = self.messages[:-1]

    def iterate(self):
        self.temperature = 0
        self.chats = list(map(lambda x: Chat(*x), self.chat_db.list_chats()))
        setMark()
        current_chat_name = self.get_chat_name()
        user_input = self.read(current_chat_name)
        self.placeholder = ""
        if not user_input:
            # Empty query means to quit.
            return False
        if user_input.settings:
            self.do_settings()
            return
        if user_input.regenerate:
            # Delete the last response and preceding prompt, and act as though
            # the user retyped it.
            # prompt.
            user_input.text = self.regenerate()
        elif user_input.edit:
            # Remove the last message, set placeholder, and ask for input again.
            self.edit()
            return True
        message = user_input.text
        if user_input.query:
            new_i = self.search(user_input.query)
            if new_i is not None:
                user_input.chat_identifier = new_i
            else:
                return True
        if user_input.message_query:
            self.search_messages(user_input.message_query)
        if user_input.chat_identifier:
            if user_input.chat_identifier < 0:
                print_formatted_text(HTML(f'<b>Starting a new chat</b>'))
                self.current_chat_id = self.new_chat()
            else:
                self.switch(user_input.chat_identifier)
            if not message:
                return True
        elif self.current_chat_id is None:
            self.current_chat_id = self.new_chat()
        if not message:
            return False
        if len(self.messages) == 1:
            self.assign_name(message)

        self.send_message(message)
        return True

    def send_message(self, message):
        draw_light_horizontal_line()
        setMark()

        self.messages.append(
            {"role": "user", "content": message},
        )
        message_id = self.chat_db.add_message(self.current_chat_id, "user", message, None, None)
        self.update_chat_fulltext()
        self.messages[-1]["id"] = message_id
        sanitized = [
                {k: v for k, v in message.items() if k != 'id'} 
                for message in self.messages]
        if self.auto_truncate:
            truncated = 0
            while len(sanitized) > 1 and self.usage(sanitized) + 500 > self.max_tokens:
                del sanitized[0]
                truncated += 1
            if truncated:
                s = "s" if truncated != 1 else ""
                print_formatted_text(HTML(f'<em>Warning: token limit exceeded. {truncated} message{s} dropped.</em>'))

        if self.allow_execution:
            execute_command.sloppy = False
            create_file.sloppy = False
            execute_python.sloppy = True
            fetch_web_page.sloppy = True
            functions = [execute_command, create_file, execute_python, fetch_web_page, summarize_web_page]
            summarize_web_page.app = self
            if os.environ.get("AZURE_KEY"):
                functions.append(bing_search)
        else:
            functions = []
        try:
            self.chat = create_chat_with_spinner(sanitized, self.temperature, functions, self.model)
        except Exception as e:
            print(f"Failed to create chat: {e}")
            return
        self.content = ""
        sh = SyntaxHighlighter()
        fspinner = None
        try:
            # There can be more than one chat when there's a function call.
            while self.read_response(functions, sh):
                pass
            sh.eof()
            print("")
            print("")
        except KeyboardInterrupt:
            sh.eof()
            self.chat.close()
            print("")
        self.commit_ordinary()

        # Check if any tasks are done.
        self.check_tasks()

    def set_model(self, model):
        self.model = model

    def validate_model(self, model):
        try:
            tiktoken.encoding_for_model(model)
        except KeyError:
            raise Exception("Unsupported model")
        return model

    def settings(self):
        return [
                Setting(
                    "Model",
                    "model",
                    lambda s: self.set_model(s),
                    "gpt-3.5-turbo",
                    lambda: self.model,
                    lambda s: self.validate_model(s)),
                Setting(
                    "Auto-truncate",
                    "auto-truncate",
                    lambda s: self.set_auto_truncate(s),
                    True,
                    lambda: self.auto_truncate,
                    lambda s: str_to_bool(s))]

    def set_auto_truncate(self, value):
        self.auto_truncate = value

    def load_settings(self):
        for setting in self.settings():
            setting.load(self.chat_db.get_setting(setting.key, setting.default))

    def print_settings(self): 
        for setting in self.settings():
            print(f'{setting.name}: {setting.value()}')

    def do_settings(self):
        self.load_settings()
        i = 1
        settings = self.settings()
        for setting in settings:
            print(f'({i}) {setting.name}: {setting.value()}')
            i += 1
        num = input("Enter the number of the setting to enter or press return to cancel: ")
        try:
            num = int(num) - 1
            if num < 0 or num >= len(settings):
                print("Invalid number")
                return
            setting = settings[num]
            value = input(f"Enter new value for {setting.name}: ")
            if not value:
                print("Cancel")
                return
            try:
                self.chat_db.set_setting(setting.key, setting.decode(value))
            except Exception as e:
                print(f"Bad value: {e}")
                return
            self.load_settings()
        except ValueError:
            print("Cancel")
            return

    def check_tasks(self):
        for task in self.tasks:
            if task.done():
                if not task.exception:
                    maybeTuple = task.result()
                    if maybeTuple is not None:
                      (chat_id, name) = maybeTuple
                      self.chat_db.set_chat_name(chat_id, name)
        self.tasks = [task for task in self.tasks if not task.done()]

    def get_chat_name(self):
        if self.current_chat_id is None:
            return "New chat"
        else:
            return self.chat_db.get_chat_name(self.current_chat_id)

    def read(self, current_chat_name):
        try:
            user_input = read_input(
                    self.chats,
                    current_chat_name,
                    len(self.messages) > 1,
                    self.placeholder,
                    self.allow_execution,
                    self.usage(self.messages),
                    self.max_tokens,
                    self.model)
            self.allow_execution = user_input.allow_execution
            return user_input 
        except KeyboardInterrupt:
            print("^C")
            exit(0)

    def message_content(self, message):
        c = message["content"]
        if c is not None:
            return c
        f = message["function_call"]
        if f is not None:
            return json.dumps(f)
        return 0

    def usage(self, messages):
        text = ""
        contents = [self.message_content(message) for message in messages]
        text = "\n".join(contents)
        return usage(self.model, text)

    def regenerate(self):
        print("Regenerating response...")
        self.delete_until_user_message()
        text = self.messages[-1]["content"]
        self.temperature = 0.5
        self.chat_db.delete_message(self.messages[-1]["id"])
        self.messages = self.messages[:-1]
        return text

    def edit(self):
        print("Editing previous message...")
        self.delete_until_user_message()
        self.placeholder = self.messages[-1]["content"]
        self.chat_db.delete_message(self.messages[-1]["id"])
        self.messages = self.messages[:-1]

    def search_messages(self, query):
        """Search messages in the current chat"""
        results = self.chat_db.search_messages_in_chat(query, self.current_chat_id)
        i = 1
        for message_id in results:
            draw_light_horizontal_line()
            print_formatted_text(HTML(f'<b>Message {i} of {len(results)}</b>'))
            i += 1
            role, content, timestamp, mid, deleted = self.chat_db.get_message_by_id(message_id)
            print_message(timestamp, role, content, deleted)
            print("")

    def search(self, query):
        """Returns id of chat to switch to or else None.
        A negative id means to create a new chat."""
        i = None
        cursor = None
        PAGE_SIZE = 10
        while True:
            search_results, cursor = self.chat_db.search_chats(query, cursor, PAGE_SIZE)
            if not len(search_results):
                print("No results")
                return None
            i = display_chat_search_results(query, search_results, self.chat_db)
            if i is None:
                cursor += PAGE_SIZE
                continue
            if i < 0:
                return -1
            return i


    def search_by_message(self, query):
        i = None
        cursor = None
        PAGE_SIZE = 10
        while True:
            search_results, cursor = self.chat_db.search_messages(query, cursor, PAGE_SIZE)
            if not len(search_results):
                print("No results")
                return None
            i = display_search_results(query, search_results, self.chat_db)
            if i is None:
                cursor += PAGE_SIZE
                continue
            if i < 0:
                return -1
            return i

    def switch(self, chat_id, show=True):
        """Replace self.messages with contents of chat_id and also print the
        messages to the screen. As a side-effect, set self.current_chat_id."""
        self.current_chat_id = chat_id
        n = self.chat_db.num_messages(self.current_chat_id)
        self.messages = []
        for i in range(1, n):
            (role, self.content, time, message_id, deleted, fname, fargs) = self.chat_db.get_message_by_index(self.current_chat_id, i)
            if self.content is not None:
                m = {
                    "id": message_id,
                    "role": role,
                    "content": self.content
                    }
                if role == "function":
                    m["name"] = fname
                else:
                    if show:
                        if role == "user":
                            draw_horizontal_line()
                        else:
                            draw_light_horizontal_line()
                        print_message(time, role, self.content.rstrip(), deleted)
                        print("")
                self.messages.append(m)
            elif fname and fargs:
                self.messages.append({
                    "id": message_id,
                    "role": "assistant",
                    "content": None,
                    "function_call": {
                        "name": fname,
                        "arguments": fargs}})

    def assign_name(self, message):
        # The chat needs a name
        self.tasks.append(BackgroundTask(lambda: suggest_name(self.current_chat_id, message)))

    def handle_function_call(self, functions, fspinner, call_name, call_args):
        try:
            if fspinner:
                fspinner.stop()
            return (None, invoke(functions, call_name, call_args), None)
        except Exception as e:
            return (None, None, str(e))

    def stop_unexpectedly(self, finish_reason):
        print("")
        print(f"Stopping because {finish_reason}")

    def read_response(self, functions, sh):
        """Read an entire response and handle it. Return True to call this again."""
        fspinner = None
        try:
            call_name = None
            call_args = None
            function_output = None
            error_output = None
            for resp in self.chat:
                if resp.choices[0].finish_reason:
                    finish_reason = resp.choices[0].finish_reason
                    if finish_reason == "function_call" and call_name and call_args:
                        fspinner, function_output, error_output = self.handle_function_call(
                                functions,
                                fspinner,
                                call_name,
                                call_args)
                    elif finish_reason != "stop":
                        self.stop_unexpectedly(finish_reason)
                    break
                elif "content" in resp.choices[0].delta and resp.choices[0].delta.content:
                    self.content = self.handle_content(resp, self.content, sh)
                elif "function_call" in resp.choices[0].delta and resp.choices[0].delta.function_call and self.allow_execution:
                    call_name, call_args, fspinner = self.accrue_function_call(
                            resp, call_name, call_args, fspinner)


            return self.commit_special(
                    call_name,
                    call_args,
                    function_output,
                    error_output,
                    functions)
        finally:
            if fspinner:
                fspinner.stop()
                fspinner = None

    def handle_content(self, resp, content, sh):
        chunk = resp.choices[0].delta.content
        content += chunk
        sh.put(chunk)
        return content

    def accrue_function_call(self, resp, call_name, call_args, fspinner):
        if "name" in resp.choices[0].delta.function_call:
            if call_name:
                call_name += resp.choices[0].delta.function_call.name
            else:
                fspinner = Spinner()
                call_name = resp.choices[0].delta.function_call.name
        if "arguments" in resp.choices[0].delta.function_call:
            if call_args:
                call_args += resp.choices[0].delta.function_call.arguments
            else:
                call_args = resp.choices[0].delta.function_call.arguments
        return (call_name, call_args, fspinner)

    def index_all_chats(self):
        if self.chat_db.get_kv("chat_fts_migration") == "done":
            return
        print("Re-indexing all chats for better full text search. This could take a second.")
        saved = self.current_chat_id
        for info in self.chat_db.list_chats():
            cid = info[0]
            self.switch(cid, False)
            self.update_chat_fulltext()
        self.current_chat_id = saved
        print("Done")
        self.chat_db.set_kv("chat_fts_migration", "done")

    def update_chat_fulltext(self):
        content = self.get_chat_name() + "\n" + "\n".join([self.plaintext_message(m) for m in self.messages])
        self.chat_db.set_chat_fulltext(self.current_chat_id, content)

    def plaintext_message(self, m):
        if m["role"] == "assistant":
            role = "Assistant"
        elif m["role"] == "user":
            role = "User"
        else:
            return ""
        if "content" not in m:
            return ""
        content = m["content"]
        return f'{role}: {content}'

    def commit_special(self, call_name, call_args, function_output,
            error_output, functions):
        if call_name and call_args:
            self.commit_function_call_request(call_name, call_args);
        if function_output:
            self.commit_function_output(functions, call_name, function_output)
            return True
        if error_output:
            return self.commit_error(error_output, functions)
        return False

    def commit_ordinary(self):
        if self.content is not None:
            self.messages.append({"role": "assistant", "content": self.content})
        message_id = self.chat_db.add_message(
                self.current_chat_id,
                self.messages[-1]["role"],
                self.messages[-1]["content"],
                None,
                None)
        self.messages[-1]["id"] = message_id
        self.update_chat_fulltext()

    def commit_function_call_request(self, call_name, call_args):
        # Record that a function call was requested
        self.messages.append({
            "role": "assistant",
            "content": None,
            "function_call": {
                "name": call_name,
                "arguments": call_args}})
        message_id = self.chat_db.add_message(self.current_chat_id,
                self.messages[-1]["role"], self.messages[-1]["content"], call_name, call_args)
        self.messages[-1]["id"] = message_id
        self.update_chat_fulltext()

    def commit_function_output(self, functions, call_name, function_output):
        # Record the output of the function call
        self.messages.append({
            "role": "function",
            "name": call_name,
            "content": function_output})
        message_id = self.chat_db.add_message(
                self.current_chat_id,
                self.messages[-1]["role"],
                self.messages[-1]["content"],
                call_name,
                None)
        self.messages[-1]["id"] = message_id
        sanitized = [
                {k: v for k, v in message.items() if k != 'id'} 
                for message in self.messages]
        try:
            self.chat = create_chat(sanitized, self.temperature, functions, self.model)
        except Exception as e:
            print(f"Failed to create chat: {e}")

    def commit_error(self, error_output, functions):
        # Something went wrong
        print(f'Error: {error_output}')
        auto_retry = False
        self.messages.append({
            "role": "system",
            "content": error_output})
        message_id = self.chat_db.add_message(
                self.current_chat_id,
                self.messages[-1]["role"],
                self.messages[-1]["content"],
                None,
                None)
        self.messages[-1]["id"] = message_id
        if auto_retry:
            sanitized = [
                    {k: v for k, v in message.items() if k != 'id'} 
                    for message in self.messages]
            print(sanitized)
            try:
                self.chat = create_chat(sanitized, self.temperature, functions, self.model)
            except Exception as e:
                print(f"Failed to create chat: {e}")
                return False
            return True
        else:
            print(f"An error was encountered while executing a function: {error_output}")
            self.content = None
            return False

def main():
    print("Welcome to gptline! Enter a question and press option-Enter to send it.")
    app = App()
    app.run_forever()

def execute_command(command_line: str, input_string: str):
    """
    Executes a unix command at the shell. Note that it does not run in a TTY so interactive commands will not work.

    Args:
        command_line: Unix command to execute. For example, "ls -l". This string will be passed to system().
        input_string: A string containing input to send to stdin.
    """
    print("")
    print("ChatGPT wants to run the following command:")
    print(command_line)
    print("")
    ok = input(f"OK to run (y/n)? ")
    if ok != "y":
        print("Not running it")
        return "Error: user denied permission to execute function call"
    print("Executing...")

    try:
        process = subprocess.Popen(command_line, shell=True, cwd="/tmp", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        output, _ = process.communicate(input=input_string)
        print("Program output:")
        print(output)
        print("")
        return output.strip()
    except Exception as e:
        print(f'Exception while executing provided code: {e}')
        return str(e)

def create_file(name: str, content: str):
    """
    Creates a file with the given name and contents.

    Args:
        name: A file name. This will be relative to a private temporary directory.
        content: A string to write to the file.
    """
    print(f"ChatGPT wants to create a file called {name} with the following contents:")
    sh = SyntaxHighlighter()
    sh.put("```")
    sh.put(content)
    sh.put("")
    sh.put("```")
    sh.eof()
    ok = input(f"OK to create (y/n)? ")
    if ok != "y":
        print("Not running it")
        return "Error: user denied permission to create file"
    file_path = os.path.join('/tmp', name)

    try:
        # Open the file in write mode and write the content
        with open(file_path, 'w') as file:
            file.write(content)
        return f"File {name} created successfully."
    except Exception as e:
        return f"Error creating file: {str(e)}"

def execute_python(code: str, input_string: Optional[str]):
    """
    Executes python code. Outputs values from stdout. If you need a computed value make sure to print() it.

    Args:
        code: Python code to execute.
        input_string: A string containing input to send to stdin.
    """
    print("ChatGPT wants to run the following Python program:")
    sh = SyntaxHighlighter()
    sh.put("```python\n")
    sh.put(code)
    if not code.endswith("\n"):
        sh.put("\n")
    sh.put("```")
    sh.eof()
    print("")
    if input_string:
        print("With this supplied as input:")
        print(input_string)
        print("")
    ok = input(f"OK to run (y/n)? ")
    if ok != "y":
        print("Not running it")
        return "Error: user denied permission to execute function call"
    print("Executing...")
    try:
        process = subprocess.Popen(["python3", "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(input=input_string if input_string else "")
        print("Program output:")
        print(stdout + stderr)
        if stderr:
            return f"Error: {stderr}"
        return stdout
    except Exception as e:
        return f"Error: {str(e)}"

def fetch_web_page(url: str):
    """
    Load a web page. Convert it to markdown and return. If something goes wrong, return a string like "404 error while fetching {url}".

    Args:
        url: The URL to fetch
    """
    print(f'Fetch {url}')
    return do_fetch(url)

def do_fetch(url):
    article = Article(url)
    article.download()
    article.parse()
    text = article.text
    if text:
        return text
    markdown_content = html2text(article.html)
    return markdown_content


def bing_search(query: str):
    """
    Perform a web search. Returns a markdown document with search results.

    Args:
        query: The websearch query string
    """
    print(f'Search Bing for {query}')
    subscription_key = os.environ.get("AZURE_KEY")
    search_url = "https://api.bing.microsoft.com/v7.0/search"
    search_term = query
    headers = {"Ocp-Apim-Subscription-Key": subscription_key}
    params = {"q": search_term, "textDecorations": True, "textFormat": "HTML"}
    response = requests.get(search_url, headers=headers, params=params)
    response.raise_for_status()
    search_results = response.json()
    values = [f' * [{v["url"]}]({v["snippet"]})' for v in search_results["webPages"]["value"]]
    return "\n".join(values)

def summarize_web_page(url: str):
    """
    Load and summarizes a web page. Returns an English summary of the web page's contents.

    Args:
        url: The URL to fetch
    """
    content = do_fetch(url)
    model = "gpt-3.5-turbo-16k"
    if not content:
        return "The page was empty"
    c = Conversation(model, "I will give you the contents of a web page and you will return a one-paragraph summary.")
    message = TextMessage.user(truncate(content, model, 14000))
    summary = c.send(message)
    return summary

