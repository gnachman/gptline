#!/usr/bin/env python3
from src.background_task import BackgroundTask
from src.chat import create_chat, create_chat_with_spinner, suggest_name, invoke
from src.db import ChatDB
from src.formatting import print_message
from src.formatting import setMark
from src.input_reader import Chat, read_input
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import HTML
from src.search import display_search_results
from src.spin import Spinner
from src.ui_utils import draw_horizontal_line, draw_light_horizontal_line
import html
import openai
import os
import subprocess
import sys
import traceback
from typing import Optional

openai.api_key = os.environ.get("OPENAI_KEY")
if not openai.api_key:
    print("Set the environment variable OPENAI_KEY to your api secret key")
    exit(1)

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
        self.messages[-1]["id"] = message_id
        sanitized = [
                {k: v for k, v in message.items() if k != 'id'} 
                for message in self.messages]
        if self.allow_execution:
            execute_command.sloppy = False
            create_file.sloppy = False
            execute_python.sloppy = True
            functions = [execute_command, create_file, execute_python]
        else:
            functions = []
        self.chat = create_chat_with_spinner(sanitized, self.temperature, functions)
        self.content = ""
        fspinner = None
        try:
            # There can be more than one chat when there's a function call.
            while self.read_response(functions):
                pass

            print("")
            print("")
        except KeyboardInterrupt:
            self.chat.close()
            print("")
        self.commit_ordinary()

        # Check if any tasks are done.
        self.check_tasks()

    def check_tasks(self):
        for task in self.tasks:
            if task.done():
                (chat_id, name) = task.result()
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
                    self.allow_execution)
            self.allow_execution = user_input.allow_execution
            return user_input 
        except KeyboardInterrupt:
            print("^C")
            exit(0)

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

    def search(self, query):
        """Returns id of chat to switch to or else None.
        A negative id means to create a new chat."""
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

    def switch(self, chat_id):
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
                    if role == "user":
                        draw_horizontal_line()
                    else:
                        draw_light_horizontal_line()
                    print_message(time, role, html.escape(self.content.rstrip()), deleted)
                    print("")
                self.messages.append(m)
            elif fname and fargs:
                self.messages.append({
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

    def read_response(self, functions):
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
                    self.content = self.handle_content(resp, self.content)
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

    def handle_content(self, resp, content):
        chunk = resp.choices[0].delta.content
        content += chunk
        sys.stdout.write(chunk)
        sys.stdout.flush()
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
        self.chat = create_chat(sanitized, self.temperature, functions)

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
            self.chat = create_chat(sanitized, self.temperature, functions)
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
        return output.strip()
    except Exception as e:
        return str(e)

def create_file(name: str, content: str):
    """
    Creates a file with the given name and contents.

    Args:
        name: A file name. This will be relative to a private temporary directory.
        content: A string to write to the file.
    """
    print(f"ChatGPT wants to create a file called {name} with the following contents:")
    print(content)
    print("")
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
    print(code)
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
        if stderr:
            return f"Error: {stderr}"
        return stdout
    except Exception as e:
        return f"Error: {str(e)}"
