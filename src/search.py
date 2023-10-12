from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import HTML
from src.formatting import print_snippet
import html

def display_chat_search_results(query, search_results, chat_db):
    session = PromptSession()

    while True:
        for index, (chat_id, snippet) in enumerate(search_results, start=1):
            chat_name = chat_db.get_chat_name(chat_id)
            print_formatted_text(HTML(f'<b>{index}. {html.escape(chat_name)}</b>'))
            escaped_snippet = html.escape(snippet).replace('\ue000', '<b>').replace('\ue001', '</b>').replace('\n', ' ')
            print_formatted_text(HTML("    " + escaped_snippet))

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
            if 0 <= selected_index < len(search_results):
                selected_chat_id = search_results[selected_index][0]
                return selected_chat_id
            else:
                print("Invalid input. Please enter a valid number.")
        except ValueError:
            print("Invalid input. Please enter a valid number.")



def display_search_results(query, messages_by_chat, chat_db):
    session = PromptSession()

    while True:
        for index, (chat_id, message_ids) in enumerate(messages_by_chat, start=1):
            chat_name = chat_db.get_chat_name(chat_id)
            print_formatted_text(HTML(f'<b>{index}. {html.escape(chat_name)}</b>'))
            for (message_id, snippet) in message_ids:
                role, content, timestamp, _id, deleted = chat_db.get_message_by_id(message_id)
                escaped_snippet = html.escape(snippet).replace('\ue000', '<b>').replace('\ue001', '</b>').replace('\n', ' ')
                print_snippet(timestamp, role, escaped_snippet, deleted, "    ")

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


