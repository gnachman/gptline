import sqlite3
from typing import Optional
import fcntl
import os
import sys

def fullpath(file):
    xdg_root = os.getenv("XDG_ROOT")
    if xdg_root:
        return os.path.join(xdg_root, file)
    else:
        home_dir = os.path.expanduser("~")
        return os.path.join(home_dir, file)

lock_fd = None

def check_single_instance(lock_file):
    global lock_fd

    try:
      lock_fd = os.open(lock_file, os.O_CREAT | os.O_TRUNC | os.O_EXLOCK | os.O_NONBLOCK)
    except BlockingIOError:
        # Another instance is already running, so terminate
        print("Another instance is already running. Exiting.")
        sys.exit(1)

class ChatDB:
    def __init__(self, db_file=".chatgpt.db"):
        db_path = fullpath(db_file)
        check_single_instance(db_path + ".lock")
        self.conn = sqlite3.connect(db_path)
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
            content TEXT NULL,
            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted INTEGER DEFAULT 0,
            function_call_name TEXT,
            function_call_arguments TEXT,
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

    def add_message(self, chat_id: int, role: str, content: str, function_call_name: Optional[str], function_call_arguments: Optional[str]):
        cursor = self.conn.cursor()  # Create a cursor
        query = "INSERT INTO messages (chat_id, role, content, function_call_name, function_call_arguments) VALUES (?, ?, ?, ?, ?)"
        cursor.execute(query, (chat_id, role, content, function_call_name, function_call_arguments))
        self.conn.commit()
        last_message_id = cursor.lastrowid

        if content is not None and role != "function":
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
        query = "SELECT role, content, time, id, deleted, function_call_name, function_call_arguments FROM messages WHERE chat_id = ? ORDER BY id LIMIT 1 OFFSET ?"
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

