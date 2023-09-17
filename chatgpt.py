#!/usr/bin/env python3
from dataclasses import dataclass
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import HorizontalLine
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame
from typing import Optional
import datetime
import html
import os
import time
import threading

@dataclass
class UserInput:
    text: Optional[str] = None
    # -1 to create a new chat.
    chat_identifier: Optional[int] = None
    query: Optional[str] = None
    regenerate = False
    edit = False

def formattedTime(timestamp):
    dt = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone()
    return dt.strftime("%b %d, %Y at %I:%M %p")


@dataclass
class Chat:
    chat_identifier: int
    name: str
    last_update: str

def draw_light_horizontal_line():
    draw_horizontal_line("<style fg='gray'>{}</style>")

def draw_horizontal_line(style=None):
    terminal_width = os.get_terminal_size().columns
    if style:
        line = HTML(style.format('\u2500' * terminal_width))
    else:
        line = HTML('\u2500' * terminal_width)
    print_formatted_text(line)

# Returns
def read_input(chats, current_chat_name, can_regen, placeholder):
    result = UserInput()

    session = PromptSession()
    kb = KeyBindings()

    # Add a binding for the 'Enter' key to insert a newline character
    @kb.add(Keys.Enter)
    def _(event):
        event.current_buffer.insert_text('\n')

    # Add a binding for ^D to accept the input.
    @kb.add(Keys.ControlD)
    def _(event):
        buffer = event.current_buffer
        if buffer.cursor_position < len(buffer.text):
            buffer.delete()
        else:
            buffer.validate_and_handle()

    SHOW_CHAT_LIST = "$$$SHOW_CHAT_LIST"
    NEW_CHAT = "$$$NEW_CHAT"
    SEARCH = "$$$SEARCH"
    REGENERATE = "$$$REGENERATE"
    EDIT = "$$$EDIT"

    @kb.add(Keys.F2)
    def _(event):
        app = get_app()
        app.exit(result=SHOW_CHAT_LIST)

    @kb.add(Keys.F3)
    def _(event):
        app = get_app()
        app.exit(result=NEW_CHAT)

    @kb.add(Keys.F4)
    def _(event):
        app = get_app()
        app.exit(result=SEARCH)

    if can_regen:
        @kb.add(Keys.F5)
        def _(event):
            app = get_app()
            app.exit(result=REGENERATE)
        @kb.add(Keys.F6)
        def _(event):
            app = get_app()
            app.exit(result=EDIT)

    def read_search_query():
        search_session = PromptSession()
        return search_session.prompt(HTML("<b>Search: </b>"))

    def pick_chat():
        print_formatted_text(HTML(f'<b>Select a chat:</b>'))
        show_list = True
        base = 0
        PAGE_SIZE = 9
        while True:
            i = 0
            for chat in chats[base:]:
                i += 1
                if i == PAGE_SIZE + 1:
                    break
                if show_list:
                    time = formattedTime(chat.last_update)
                    print_formatted_text(f'{i}: {chat.name} ({time})')
            show_list = True

            kb = KeyBindings()
            user_pressed_esc = [False]
            @kb.add(Keys.ControlD)
            def _(event):
                user_pressed_esc[0] = True
                event.app.exit()

            # Prompt the user for their selection
            picker_session = PromptSession(key_bindings=kb)
            selection = picker_session.prompt(HTML("<b>Enter chat number, press 'return' for more, + to create a new chat, or '^D' to cancel: </b>"))

            if user_pressed_esc[0]:
                return

            # Handle the user's selection
            if selection.isdigit():
                index = int(selection) + base - 1
                result.chat_identifier = chats[index].chat_identifier
                print_formatted_text(HTML(f'<b>Switched to: {html.escape(chats[index].name)}</b>'))
                return
            elif selection == '':
                if len(chats) > base + PAGE_SIZE:
                    base += PAGE_SIZE
                else:
                    print_formatted_text(HTML('<b>No more chats.</b>'))
                    show_list = False
            elif selection == '+':
                result.chat_identifier = -1
                return
            else:
                print_formatted_text(HTML('<b>Selection canceled or invalid choice.</b>'))


    # Create a frame around the default buffer
    frame = Frame(body=Window(content=BufferControl(buffer=session.default_buffer)))

    # Set the layout of the session to use the frame
    session.layout = Layout(container=frame)

    # Prompt the user for input
    draw_horizontal_line()
    try:
        while True:
            def bottom_toolbar():
                text = f'[{html.escape(current_chat_name)}] <b>^D</b>: Send  <b>F2</b>: Switch chat  <b>F3</b>: New chat  <b>F4</b>: Search'
                if can_regen:
                    text += "  <b>F5</b>: Regenerate"
                    text += "  <b>F6</b>: Edit Last"
                return HTML(text)
            value = session.prompt(
                    "",
                key_bindings=kb,
                multiline=True,
                bottom_toolbar=bottom_toolbar,
                default=placeholder
            )
            if value == SHOW_CHAT_LIST:
                pick_chat()
                if result.chat_identifier is not None:
                    return result
            elif value == NEW_CHAT:
                result.chat_identifier = -1
                return result
            elif value == REGENERATE:
                result.regenerate = True
                return result
            elif value == EDIT:
                result.edit = True
                return result
            elif value == SEARCH:
                try:
                    result.query = read_search_query()
                    if result.query is not None:
                        return result
                except EOFError:
                    pass
            else:
                result.text = value
                return result
    except Exception as e:
        print(e)
        return None


import sqlite3

class ChatDB:
    def __init__(self, db_file="saved_chat.db"):
        self.conn = sqlite3.connect(db_file)
        self.create_schema()

    def create_schema(self):
        query = """
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        self.conn.execute(query)

        query = """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            role TEXT,
            content TEXT,
            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted INTEGER DEFAULT 0,
            FOREIGN KEY (chat_id) REFERENCES chats (id)
        )
        """
        self.conn.execute(query)

        query = """
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING FTS5 (
            message_id UNINDEXED,
            content,
            content_rowid,
        )
        """
        self.conn.execute(query)

    def create_chat(self, name=None):
        cursor = self.conn.cursor()  # Create a cursor
        query = "INSERT INTO chats (name) VALUES (?)"
        cursor.execute(query, (name,))
        chat_id = cursor.lastrowid  # Access lastrowid from the cursor
        self.conn.commit()
        return chat_id

    def add_message(self, chat_id: int, role: str, content: str):
        cursor = self.conn.cursor()  # Create a cursor
        query = "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)"
        cursor.execute(query, (chat_id, role, content))
        self.conn.commit()
        last_message_id = cursor.lastrowid

        fts_query = "INSERT INTO messages_fts (message_id, content) VALUES (?, ?)"
        self.conn.execute(fts_query, (last_message_id, content.lower()))
        self.conn.commit()

        query = f"UPDATE chats SET last_update = CURRENT_TIMESTAMP WHERE id = ?"
        cursor.execute(query, (chat_id, ))

        return last_message_id

    def num_messages(self, chat_id: int) -> int:
        query = "SELECT COUNT(*) FROM messages WHERE chat_id = ?"
        result = self.conn.execute(query, (chat_id,)).fetchone()
        return result[0]

    def get_message_by_id(self, message_id: int):
        query = "SELECT role, content, time, id, deleted FROM messages WHERE id = ?"
        result = self.conn.execute(query, (message_id,)).fetchone()
        if result:
            return result
        else:
            raise IndexError("Index out of range")

    def get_message_by_index(self, chat_id: int, index: int):
        query = "SELECT role, content, time, id, deleted FROM messages WHERE chat_id = ? ORDER BY id LIMIT 1 OFFSET ?"
        result = self.conn.execute(query, (chat_id, index)).fetchone()
        if result:
            return result
        else:
            raise IndexError("Index out of range")

    def list_chats(self):
        query = "SELECT id, name, last_update FROM chats ORDER BY id DESC"
        result = self.conn.execute(query).fetchall()
        return result

    def set_chat_name(self, chat_id: int, name: str):
        query = "UPDATE chats SET name = ? WHERE id = ?"
        self.conn.execute(query, (name, chat_id))
        self.conn.commit()

    def get_chat_name(self, chat_id):
        query = "SELECT name FROM chats WHERE id = ?"
        cursor = self.conn.execute(query, (chat_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            return None

    def delete_message(self, message_id: int):
        query = """
        UPDATE messages
        SET deleted = 1
        WHERE id = ?
        """
        self.conn.execute(query, (message_id,))
        self.conn.commit()

    def search_messages(self, query: str, pagination_token: int, limit: int):
        fts_query = """
            SELECT m.id, m.chat_id, snippet(messages_fts, 1, '\ue000', '\ue001', '...', 16) AS snippet 
            FROM messages_fts 
            JOIN messages m ON messages_fts.message_id = m.id 
            WHERE messages_fts.content MATCH ?
            LIMIT ?
            OFFSET ?
        """

        if pagination_token is None:
            offset = 0
        else:
            offset = pagination_token

        parameters = (query.lower(), limit, offset)

        result = self.conn.execute(fts_query, parameters)

        message_ids = []
        chat_ids = []
        snippets = {}
        for row in result:
            message_ids.append(int(row[0]))
            snippets[int(row[0])] = row[2]
            chat_ids.append(int(row[1]))

        # Sort chat IDs
        sorted_chat_ids = sorted(set(chat_ids))

        messages_by_chat = []
        for chat_id in sorted_chat_ids:
            message_ids_for_chat = [(message_ids[i], snippets[message_ids[i]]) for i in range(len(message_ids)) if chat_ids[i] == chat_id]
            messages_by_chat.append((chat_id, message_ids_for_chat))

        # Determine the pagination token
        next_offset = offset + limit
        has_more_results = len(message_ids) > next_offset
        pagination_token = next_offset if has_more_results else None

        return messages_by_chat, offset + len(message_ids)

class BackgroundTask:
    def __init__(self, func):
        self._thread = threading.Thread(target=self._run, args=(func,))
        self._result = None
        self._done = False
        self._thread.start()

    def _run(self, func):
        self._result = func()
        self._done = True

    def done(self):
        return self._done

    def result(self):
        return self._result

import openai
import sys
openai.api_key = os.environ.get("OPENAI_KEY")
if not openai.api_key:
    print("Set the environment variable OPENAI_KEY to your api secret key")
    exit(1)

from itertools import product

def print_message(timestamp, role, content, deleted, prefix=""):
    s = prefix + f"[{formattedTime(timestamp)}] <i>{role}</i>: {content}"
    if deleted:
        print_formatted_text(HTML("<strike>" + s + "</strike>"))
    else:
        print_formatted_text(HTML(s))

def display_search_results(query, messages_by_chat, chat_db):
    session = PromptSession()

    while True:
        for index, (chat_id, message_ids) in enumerate(messages_by_chat, start=1):
            chat_name = chat_db.get_chat_name(chat_id)
            print_formatted_text(HTML(f'<b>{index}. {html.escape(chat_name)}</b>'))
            for (message_id, snippet) in message_ids:
                role, content, timestamp, _id, deleted = chat_db.get_message_by_id(message_id)
                escaped_snippet = html.escape(snippet).replace('\ue000', '<b>').replace('\ue001', '</b>').replace('\n', ' ')
                print_message(timestamp, role, escaped_snippet, deleted, "    ")

        # Prompt the user to either select a chat or request more results
        try:
            user_input = session.prompt("\nEnter a number to select a chat, press Enter for more results, or Ctrl+D to cancel: ")
        except EOFError:
            print("\nSearch canceled.")
            return -1
        except KeyboardInterrupt:
            print("\nSearch canceled.")
            return -1

        # Return None to request more results
        if user_input == "":
            return None

        # Return chat ID as int if selected
        try:
            selected_index = int(user_input) - 1
            if 0 <= selected_index < len(messages_by_chat):
                selected_chat_id = messages_by_chat[selected_index][0]
                return selected_chat_id
            else:
                print("Invalid input. Please enter a valid number.")
        except ValueError:
            print("Invalid input. Please enter a valid number.")

def create_chat_with_spinner(messages, temperature):
    chats = []

    def show_spinner():
        spinner = ["|", "/", "-", "\\"]
        i = 0
        while len(chats) == 0:
            sys.stdout.write("\r" + spinner[i % 4])
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1


    def create_chat_model():
        chat = openai.ChatCompletion.create(
            model="gpt-3.5-turbo", messages=messages, stream=True, temperature=temperature
        )
        chats.append(chat)

    thread = threading.Thread(target=create_chat_model)
    thread.start()

    spinner_thread = threading.Thread(target=show_spinner)
    spinner_thread.start()

    thread.join()
    spinner_thread.join()

    sys.stdout.write("\r \r")
    return chats[0]

def suggest_name(chat_id, message):
    chat_completion_resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You assign names to conversations based on the first message. Respond with only a short, descriptive title for a conversation."},
            {"role": "user", "content": message}
        ],
        temperature=0,
        max_tokens=10
    )
    name = chat_completion_resp.choices[0].message.content
    return (chat_id, name)

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
        user_input = read_input(chats, current_chat_name, len(messages) > 1, placeholder)
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
                print(f'Switch to {user_input.chat_identifier}')
                current_chat_id = user_input.chat_identifier
                n = chat_db.num_messages(current_chat_id)
                messages = []
                for i in range(n):
                    (role, content, time, message_id, deleted) = chat_db.get_message_by_index(current_chat_id, i)
                    if role == "user":
                        draw_horizontal_line()
                    else:
                        draw_light_horizontal_line()
                    print_message(time, role, html.escape(content.rstrip()), deleted)
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
                sys.stdout.write(chunk)
                sys.stdout.flush()
            print("")
            print("")
        except KeyboardInterrupt:
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

def setMark():
    if 'TERM' in os.environ and os.environ['TERM'].startswith('screen'):
        osc = "\033Ptmux;\033\033]"
        st = "\a\033\\"
    else:
        osc = "\033]"
        st = "\a"

    print(f"{osc}1337;SetMark{st}", end='')

chat_loop()
