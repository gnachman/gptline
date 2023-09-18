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

def delete_until_user_message(chat_db, messages):
     while messages[-1]["role"] == "assistant" or messages[-1]["role"] == "function" or "function_call" in messages[-1]:
         chat_db.delete_message(messages[-1]["id"])
         messages = messages[:-1]
     return messages

def main():
    tasks = []
    chat_db = ChatDB()
    current_chat_id = None
    messages = []

    def new_chat():
        current_chat_id = chat_db.create_chat("New chat")
        messages.clear()
        messages.append({
            "role": "system",
            "content": "You assist a user in a terminal emulator."})
        chat_db.add_message(current_chat_id, messages[0]["role"], messages[0]["content"], None, None)
        return current_chat_id

    placeholder = ""
    allow_execution = False
    while True:
        temperature = 0
        chats = list(map(lambda x: Chat(*x), chat_db.list_chats()))
        setMark()
        if current_chat_id is None:
            current_chat_name = "New chat"
        else:
            current_chat_name = chat_db.get_chat_name(current_chat_id)
        try:
            user_input = read_input(chats, current_chat_name, len(messages) > 1, placeholder, allow_execution)
            allow_execution = user_input.allow_execution
        except KeyboardInterrupt:
            print("^C")
            exit(0)
        placeholder = ""
        if not user_input:
            break
        if user_input.regenerate:
            print("Regenerating response...")
            messages = delete_until_user_message(chat_db, messages)
            user_input.text = messages[-1]["content"]
            temperature = 0.5
            print(user_input.text)
            chat_db.delete_message(messages[-1]["id"])
            messages = messages[:-1]
        elif user_input.edit:
            print("Editing previous message...")
            messages = delete_until_user_message(chat_db, messages)
            placeholder = messages[-1]["content"]
            chat_db.delete_message(messages[-1]["id"])
            messages = messages[:-1]
            continue

        message = user_input.text
        if user_input.query:
            i = None
            cursor = None
            PAGE_SIZE = 10
            while True:
                search_results, cursor = chat_db.search_messages(user_input.query, cursor, PAGE_SIZE)
                if not len(search_results):
                    print("No results")
                    break
                i = display_search_results(user_input.query, search_results, chat_db)
                if i is None:
                    cursor += PAGE_SIZE
                    continue
                if i < 0:
                    break
                user_input.chat_identifier = i
                break
            if i is None or i < 0:
                continue

        if user_input.chat_identifier:
            if user_input.chat_identifier < 0:
                print_formatted_text(HTML(f'<b>Starting a new chat</b>'))
                current_chat_id = new_chat()
            else:
                current_chat_id = user_input.chat_identifier
                n = chat_db.num_messages(current_chat_id)
                messages = []
                for i in range(n):
                    (role, content, time, message_id, deleted, fname, fargs) = chat_db.get_message_by_index(current_chat_id, i)
                    if content is not None:
                        m = {
                            "id": message_id,
                            "role": role,
                            "content": content
                            }
                        if role == "function":
                            m["name"] = fname
                        else:
                            if role == "user":
                                draw_horizontal_line()
                            else:
                                draw_light_horizontal_line()
                            print_message(time, role, html.escape(content.rstrip()), deleted)
                            print("")
                        messages.append(m)
                    elif fname and fargs:
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "function_call": {
                                "name": fname,
                                "arguments": fargs}})

            if not message:
                continue
        elif current_chat_id is None:
            current_chat_id = new_chat()
        if not message:
            return
        if len(messages) == 1:
            # The chat needs a name
            tasks.append(BackgroundTask(lambda: suggest_name(current_chat_id, message)))

        draw_light_horizontal_line()
        setMark()

        messages.append(
            {"role": "user", "content": message},
        )
        message_id = chat_db.add_message(current_chat_id, "user", message, None, None)
        messages[-1]["id"] = message_id
        sanitized = [{k: v for k, v in message.items() if k != 'id'} for message in messages]
        if allow_execution:
            functions = [execute_command, create_file, execute_python]
        else:
            functions = []
        chat = create_chat_with_spinner(sanitized, temperature, functions)
        content = ""
        fspinner = None
        try:
            # There can be more than one chat when there's a function call.
            while True:
                call_name = None
                call_args = None
                function_output = None
                error_output = None
                fspinner = None

                # Iterate over streaming tokens in the chat.
                for resp in chat:
                    if resp.choices[0].finish_reason:
                        finish_reason = resp.choices[0].finish_reason
                        if finish_reason == "function_call" and call_name and call_args:
                            try:
                                if fspinner:
                                    fspinner.stop()
                                    fspinner = None
                                function_output = invoke(functions, call_name, call_args)
                            except Exception as e:
                                error_output = str(e)
                        elif finish_reason != "stop":
                            print("")
                            print(f"Stopping because {finish_reason}")
                        break
                    elif "content" in resp.choices[0].delta and resp.choices[0].delta.content:
                        chunk = resp.choices[0].delta.content
                        content += chunk
                        sys.stdout.write(chunk)
                        sys.stdout.flush()
                    elif "function_call" in resp.choices[0].delta and resp.choices[0].delta.function_call and allow_execution:
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

                if call_name and call_args:
                    # Record that a function call was requested
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "function_call": {
                            "name": call_name,
                            "arguments": call_args}})
                    message_id = chat_db.add_message(current_chat_id, messages[-1]["role"], messages[-1]["content"], call_name, call_args)
                    messages[-1]["id"] = message_id
                if function_output:
                    # Record the output of the function call
                    messages.append({
                        "role": "function",
                        "name": call_name,
                        "content": function_output})
                    message_id = chat_db.add_message(current_chat_id, messages[-1]["role"], messages[-1]["content"], call_name, None)
                    messages[-1]["id"] = message_id
                    sanitized = [{k: v for k, v in message.items() if k != 'id'} for message in messages]
                    chat = create_chat(sanitized, temperature, functions)
                    continue
                if error_output:
                    # Something went wrong
                    print(f'Error: {error_output}')
                    auto_retry = False
                    messages.append({
                        "role": "system",
                        "content": error_output})
                    message_id = chat_db.add_message(current_chat_id, messages[-1]["role"], messages[-1]["content"], None, None)
                    messages[-1]["id"] = message_id
                    if auto_retry:
                        sanitized = [{k: v for k, v in message.items() if k != 'id'} for message in messages]
                        print(sanitized)
                        chat = create_chat(sanitized, temperature, functions)
                        continue
                    else:
                        print(f"An error was encountered while executing a function: {error_output}")
                        content = None

                break

            print("")
            print("")
        except KeyboardInterrupt:
            chat.close()
            print("")
        if fspinner:
            fspinner.stop()
            fspinner = None
        if content is not None:
            messages.append({"role": "assistant", "content": content})
        message_id = chat_db.add_message(current_chat_id, messages[-1]["role"], messages[-1]["content"], None, None)
        messages[-1]["id"] = message_id

        # Check if any tasks are done.
        for task in tasks:
            if task.done():
                (chat_id, name) = task.result()
                chat_db.set_chat_name(chat_id, name)
            tasks = [task for task in tasks if not task.done()]


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
