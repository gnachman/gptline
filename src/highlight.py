from blessings import Terminal
from dataclasses import dataclass
import re
import sys
import termios
import tty
import uuid
from pygments.lexers import get_lexer_by_name
from pygments import highlight
from pygments.formatters import TerminalTrueColorFormatter
from pygments.style import Style
from pygments.token import Token
from pygments.styles import get_style_by_name


@dataclass
class Theme:
    code_block_banner_bg: str
    code_block_banner_fg: str
    code_block_bg: str
    inline_code: str

def foreground_color(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"

def background_color(r, g, b):
    return f"\033[48;2;{r};{g};{b}m"

class SyntaxHighlighter:
    def __init__(self):
        self.term = Terminal()
        self.buffer = ""
        self.is_bold = False
        self.is_italic = False
        self.is_underline = False
        self.is_inline_code = False
        self.is_block_code = False
        self.block_id = None
        self.will_enter_block_code = False
        self.prev_attrs = []
        self.markup_eligible = True
        self.line = ""
        self.language = None
        darkTheme = Theme(background_color(55, 55, 55),
                          foreground_color(215, 215, 215),
                          background_color(15, 15, 15),
                          self.term.bold)

        lightTheme = Theme(background_color(215, 215, 215),
                           foreground_color(15, 15, 15),
                           background_color(240, 240, 240),
                           self.term.bold)

        if is_background_dark():
            self.theme = darkTheme
            self.formatter = TerminalTrueColorFormatter()
        else:
            self.theme = lightTheme
            self.formatter = TerminalTrueColorFormatter()
        self.lexer = None
        self.lex_buffer = ""

    def put(self, s):
        self._put(s)
        sys.stdout.flush()

    def _put(self, s):
        if len(s) == 0:
            return

        self.buffer += s
        while len(self.buffer) > 0:
            if not self.is_block_code and self.buffer.startswith("**"):
                self.is_bold = not self.is_bold
                self.buffer = self.buffer[2:]
            elif not self.is_block_code and self.buffer.startswith("*") and len(self.buffer) > 1 and self.buffer[1] != "*" and self.buffer[1] != " " and self.buffer[1] != "\n":
                self.is_italic = not self.is_italic
                self.buffer = self.buffer[1:]
            elif not self.is_block_code and self.buffer == "*":
                return
            elif not self.is_block_code and self.buffer.startswith("_") and self.markup_eligible:
                self.is_underline = not self.is_underline
                self.buffer = self.buffer[1:]
            elif not self.is_inline_code and self.buffer == "`":
                # A single backtick is ambiguous. Could be an inline block or a code block.
                return
            elif not self.is_block_code and not self.is_inline_code and self.buffer.startswith("`") and len(self.buffer) > 1 and self.buffer[1] != "`" and self.line and self.line[-1] == ' ':
                # Start an inline block
                self.is_inline_code = True
                self.buffer = self.buffer[1:]
            elif not self.is_block_code and self.is_inline_code and self.buffer.startswith("\n"):
                # End an inline block at newline to avoid it running away
                self.is_inline_code = False
            elif not self.is_block_code and self.is_inline_code and self.buffer.startswith("`"):
                # End an inline block
                self.is_inline_code = False
                self.buffer = self.buffer[1:]
            elif not self.is_block_code and not self.will_enter_block_code and re.match(r'^[ ]{0,8}$', self.line) is not None and self.buffer.startswith("```"):
                # Start a code block
                if '\n' not in self.buffer[1:]:
                    # Ignore language, which follows ```
                    return
                self.is_block_code = True
                self.block_id = uuid.uuid4()
                self.will_enter_block_code = True
                # Remove up to and including first newline
                first, second = self.buffer.split('\n', 1)
                if len(first) > 4:
                  # Print language
                  print(self.theme.code_block_banner_bg + self.theme.code_block_banner_fg, end='')
                  print(first[3:] + self.erase_line() + "    " + self.copyButton(self.block_id) + " " + self.hyperlink(f"iterm2:copy-block?block={self.block_id}", "Copy to clipboard") + self.term.normal)
                  self.language = first[3:]
                else:
                  self.language = "text/plain"
                try:
                    self.lexer = get_lexer_by_name(first[3:])
                except:
                    pass
                self.prev_attrs = None
                self.buffer = second
            elif self.is_block_code and not self.will_enter_block_code and self.buffer.startswith("```\n"):
                # End a code block
                if not self.will_enter_block_code:
                    self.emit(self.end_block(self.block_id) + self.term.normal)
                self.block_id = None
                self.will_enter_block_code = False
                self.buffer = self.buffer[4:]
                self.is_block_code = False
                self.lexer = None
            elif self.is_block_code and (self.buffer == "`" or self.buffer == "``"):
                # Too soon to tell
                return
            elif not self.is_block_code and re.match(r"\[.*\]\(.*\)", self.buffer):
                link_text, link_url = re.findall(r"\[(.*?)\]\((.*?)\)", self.buffer)[0]
                self.buffer = self.buffer[len(link_text) + len(link_url) + 4:]
                self.emit(self.hyperlink(link_url, link_text))
            elif not self.is_block_code and (self.buffer.startswith('[') or self.buffer == "``") and '\n' not in self.buffer:
                return
            else:
                self.printFirst()

    def copyButton(self, block_id):
        return self.osc(1337) + f'Button=type=copy;block={block_id}' + self.st()

    def erase_line(self):
        return '\033[K'

    def osc(self, n):
        return f'\033]{n};'

    def st(self):
        return f'\a'

    def hyperlink(self, href, anchor):
        return self.osc(8) + f';{href}' + self.st() + anchor + self.osc(8) + ';' + self.st()

    def start_block(self, id, type):
        return self.osc(1337) + f'Block=attr=start;id={id};type={type}' + self.st()

    def end_block(self, id):
        return self.osc(1337) + f'Block=attr=end;id={id};render=0' + self.st()

    def eof(self):
        while len(self.buffer) > 0:
            self.printFirst()
        if self.is_block_code:
            self.emit(self.end_block(self.block_id))

    def lex(self):
        highlighted_code = highlight(self.lex_buffer, self.lexer, self.formatter)
        highlighted_code = highlighted_code.replace("\n", self.theme.code_block_bg + self.erase_line() + "\n")
        print(highlighted_code, end='')
        self.lex_buffer = ""

    def printFirst(self):
        attrs = []
        if self.is_block_code:
            attrs.append(self.theme.code_block_bg)
        if self.will_enter_block_code:
            self.emit(self.theme.code_block_bg + self.erase_line())
            self.emit(self.start_block(self.block_id, self.language))
            self.will_enter_block_code = False
            attrs.append(self.theme.code_block_bg)
        if self.lexer:
            if self.buffer[0] == "\n":
                self.lex()
                self.line = ""
            else:
                self.lex_buffer += self.buffer[0]
            self.buffer = self.buffer[1:]
            return

        if self.is_bold:
            attrs.append(self.term.bold)
        elif self.is_italic:
            attrs.append(self.term.italic)
        elif self.is_underline:
            attrs.append(self.term.underline)
        elif self.is_inline_code:
            attrs.append(self.theme.inline_code)
        if self.prev_attrs != attrs:
            self.emit(self.term.normal + "".join(attrs) + self.buffer[0])
            self.prev_attrs = attrs
        else:
            self.emit(self.buffer[0])
        self.markup_eligible = self.buffer[0] == ' ' or self.buffer[0] == '\n'

        if self.buffer[0] == "\n":
            self.line = ""
            self.emit(self.erase_line())
        else:
            self.line += self.buffer[0]
        self.buffer = self.buffer[1:]

    def emit(self, chunk):
        print(chunk, end='')

def is_background_dark():
    # Save the current terminal settings
    old_settings = termios.tcgetattr(sys.stdin)

    try:
        # Set the terminal to raw mode
        tty.setraw(sys.stdin)

        # Write the query control sequence to the terminal
        sys.stdout.write('\033]11;?\033\\')
        sys.stdout.flush()

        # Read the response from the terminal
        response = ''
        while True:
            char = sys.stdin.read(1)
            response += char
            if response.endswith('\033\\'):
                break

        # Extract the background color information from the response
        match = re.search(r'rgb:([0-9a-fA-F]{4})/([0-9a-fA-F]{4})/([0-9a-fA-F]{4})', response)
        if match:
            r = int(match.group(1), 16)
            g = int(match.group(2), 16)
            b = int(match.group(3), 16)
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 1000
            return luminance < 0.5

        return False

    finally:
        # Restore the terminal settings
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
