#!/usr/bin/env python3
from src.background_task import BackgroundTask
from src.chat import create_chat_with_spinner, suggest_name
from src.db import ChatDB
from src.formatting import print_message
from src.formatting import setMark
from src.highlight import SyntaxHighlighter
from src.input_reader import Chat, read_input
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import HTML
from src.search import display_search_results
from src.ui_utils import draw_horizontal_line, draw_light_horizontal_line
import html
import openai
import os
import sys

openai.api_key = os.environ.get("OPENAI_KEY")
if not openai.api_key:
    print("Set the environment variable OPENAI_KEY to your api secret key")
    exit(1)

def chat_loop():
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
        chat_db.add_message(current_chat_id, messages[0]["role"], messages[0]["content"])
        return current_chat_id

    placeholder = ""
    while True:
        temperature = 0
        chats = list(map(lambda x: Chat(*x), chat_db.list_chats()))
        setMark()
        if current_chat_id is None:
            current_chat_name = "New chat"
        else:
            current_chat_name = chat_db.get_chat_name(current_chat_id)
        try:
            user_input = read_input(chats, current_chat_name, len(messages) > 1, placeholder)
        except KeyboardInterrupt:
            print("^C")
            exit(0)
        placeholder = ""
        if not user_input:
            break
        if user_input.regenerate:
            print("Regenerating response...")
            user_input.text = messages[-2]["content"]
            temperature = 0.5
            print(user_input.text)
            chat_db.delete_message(messages[-1]["id"])
            chat_db.delete_message(messages[-2]["id"])
            messages = messages[:-2]
        elif user_input.edit:
            print("Editing previous message...")
            placeholder = messages[-2]["content"]
            chat_db.delete_message(messages[-1]["id"])
            chat_db.delete_message(messages[-2]["id"])
            messages = messages[:-2]
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
                    (role, content, time, message_id, deleted) = chat_db.get_message_by_index(current_chat_id, i)
                    if role == "user":
                        draw_horizontal_line()
                    else:
                        draw_light_horizontal_line()
                    print_message(time, role, content.rstrip(), deleted)
                    print("")
                    messages.append({
                        "id": message_id,
                        "role": role,
                        "content": content
                        })
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
        message_id = chat_db.add_message(current_chat_id, "user", message)
        messages[-1]["id"] = message_id
        sanitized = [{k: v for k, v in message.items() if k != 'id'} for message in messages]
        chat = create_chat_with_spinner(sanitized, temperature)
        content = ""
        sh = SyntaxHighlighter()
        try:
            for resp in chat:
                if resp.choices[0].finish_reason:
                    finish_reason = resp.choices[0].finish_reason
                    if finish_reason != "stop":
                        print("")
                        print(f"Stopping because {finish_reason}")
                    break
                chunk = resp.choices[0].delta.content
                content += chunk
                sh.put(chunk)
            sh.eof()
            print("")
            print("")
        except KeyboardInterrupt:
            sh.eof()
            chat.close()
            print("")
        messages.append({"role": "assistant", "content": content})
        message_id = chat_db.add_message(current_chat_id, messages[-1]["role"], messages[-1]["content"])
        messages[-1]["id"] = message_id

        # Check if any tasks are done.
        for task in tasks:
            if task.done():
                (chat_id, name) = task.result()
                chat_db.set_chat_name(chat_id, name)
            tasks = [task for task in tasks if not task.done()]

chat_loop()
