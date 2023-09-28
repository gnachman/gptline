import simplejson
import enum
import inspect
import openai
import sys
import threading
import time
import typing
from src.spin import spin

def get_json_type_name(value):
    if isinstance(value, str):
        return "string"
    elif isinstance(value, int):
        return "integer"
    elif isinstance(value, float):
        return "number"
    elif isinstance(value, bool):
        return "boolean"
    else:
        return "null"

def _json_schema(func):
    api_info = {}

    # Get function name
    api_info["name"] = func.__name__

    # Get function description from docstring
    docstring = inspect.getdoc(func)
    if docstring:
        api_info["description"] = docstring.split("\n\n")[0]

    # Get function parameters
    parameters = {}
    parameters["type"] = "object"

    properties = {}

    signature = inspect.signature(func)
    required = []
    for param_name, param in signature.parameters.items():
        param_info = {}

        # Get parameter type from type hints
        if typing.get_origin(param.annotation) is typing.Union and type(None) in typing.get_args(param.annotation):
            # Handle Optional case
            inner_type = typing.get_args(param.annotation)[0]
            if issubclass(inner_type, enum.Enum):
                param_info["type"] = get_json_type_name(inner_type.__members__[list(inner_type.__members__)[0]].value)
                param_info["enum"] = [member.value for member in inner_type]
            else:
                param_info["type"] = get_json_type_name(inner_type.__name__)
        elif issubclass(param.annotation, enum.Enum):
            param_info["type"] = get_json_type_name(param.annotation.__members__[list(param.annotation.__members__)[0]].value)
            param_info["enum"] = [member.value for member in param.annotation]
        else:
            param_info["type"] = get_json_type_name(param.annotation.__name__)

        # Get parameter description from docstring
        if docstring and param_name in docstring:
            param_info["description"] = docstring.split(param_name + ":")[1].split("\n")[0].strip()

        # Check if parameter is required
        if param.default == inspect.Parameter.empty:
            required.append(param_name)

        # Add parameter info to parameters dict
        properties[param_name] = param_info

    # Add parameters to api_info
    parameters["properties"] = properties
    parameters["required"] = required
    api_info["parameters"] = parameters

    return api_info

def create_chat_with_spinner(messages, temperature, functions, model):
    return create_chat(messages, temperature, functions, model, True)

def create_chat(messages, temperature, functions, model, spinner=False):
    def create_chat_model():
        args = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
        }
        if functions:
            args['functions'] = list(map(lambda f: _json_schema(f), functions))
        return openai.ChatCompletion.create(**args)

    if not spinner:
        chats = []
        return create_chat_model()
    else:
        return spin(create_chat_model)


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

def invoke(functions, name, args_str):
    try:
        args = simplejson.loads(args_str, strict=False)
    except Exception as e:
        return invoke_sloppy(functions, name, args_str)

    for func in functions:
        if func.__name__ == name:
            return func(**args)
    else:
        raise ValueError(f"Function '{name}' not found.")

def invoke_sloppy(functions, name, args_str):
    for func in functions:
        if func.__name__ == name and func.sloppy:
            args = [None] * len(inspect.signature(func).parameters)
            args[0] = args_str
            return func(*args)
    else:
        raise ValueError(f"Function '{name}' not found.")
