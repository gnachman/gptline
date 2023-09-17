import os
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit import PromptSession, print_formatted_text

def draw_light_horizontal_line():
    draw_horizontal_line("<style fg='gray'>{}</style>")

def draw_horizontal_line(style=None):
    terminal_width = os.get_terminal_size().columns
    if style:
        line = HTML(style.format('\u2500' * terminal_width))
    else:
        line = HTML('\u2500' * terminal_width)
    print_formatted_text(line)


