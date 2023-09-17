import sys
import time
import openai
import threading

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

