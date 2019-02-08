from __future__ import absolute_import

import inspect
import keyword
import linecache
import os
import re
import sys
import tokenize
import traceback

from .color import SUPPORTS_COLOR
from .highlighter import STYLE, Highlighter
from .repl import get_repl


THEME = {
    'introduction': '\x1b[33m\x1b[1m{}\x1b[m',
    'cause': '\x1b[1m{}\x1b[m',
    'context': '\x1b[1m{}\x1b[m',
    'dirname': '\x1b[32m{}\x1b[m',
    'basename': '\x1b[32m\x1b[1m{}\x1b[m',
    'lineno': '\x1b[33m{}\x1b[m',
    'function': '\x1b[35m{}\x1b[m',
    'exception_type': '\x1b[31m\x1b[1m{}\x1b[m',
    'exception_value': '\x1b[1m{}\x1b[m',
    'arrows': '\x1b[36m{}\x1b[m',
    'value': '\x1b[36m\x1b[1m{}\x1b[m',
}

MAX_LENGTH = 128


class ExceptionFormatter(object):

    CMDLINE_REGXP = re.compile(r'(?:[^\t ]*([\'"])(?:\\.|.)*(?:\1))[^\t ]*|([^\t ]+)')

    def __init__(self, colored=SUPPORTS_COLOR, style=STYLE, theme=THEME, max_length=MAX_LENGTH,
                       encoding='ascii'):
        self._colored = colored
        self._theme = theme
        self._max_length = max_length
        self._encoding = encoding
        self._highlighter = Highlighter(style)
        self._pipe_char = self._get_char('\u2502', '|')
        self._cap_char = self._get_char('\u2514', '->')

    def _get_char(self, char, default):
        try:
            char.encode(self._encoding)
        except UnicodeEncodeError:
            return default
        else:
            return char

    def _colorize_filepath(self, filepath):
        dirname, basename = os.path.split(filepath)

        if dirname:
            dirname += os.sep

        dirname = self._theme["dirname"].format(dirname)
        basename = self._theme["basename"].format(basename)

        return dirname + basename

    def format_value(self, v):
        try:
            v = repr(v)
        except Exception:
            v = '<unprintable %s object>' % type(v).__name__

        max_length = self._max_length
        if max_length is not None and len(v) > max_length:
            v = v[:max_length] + '...'
        return v

    def get_relevant_values(self, source, frame):
        values = []
        value = None
        is_attribute = False
        is_valid_value = False

        for token in self._highlighter.tokenize(source):
            type_, string, (_, col), *_ = token

            if type_ == tokenize.NAME and not keyword.iskeyword(string):
                if not is_attribute:
                    for variables in (frame.f_locals, frame.f_globals):
                        try:
                            value = variables[string]
                        except KeyError:
                            continue
                        else:
                            is_valid_value = True
                            values.append((col, self.format_value(value)))
                            break
                elif is_valid_value:
                    try:
                        value = inspect.getattr_static(value, string)
                    except AttributeError:
                        is_valid_value = False
                    else:
                        values.append((col, self.format_value(value)))
            elif type_ == tokenize.OP and string == ".":
                is_attribute = True
            else:
                is_attribute = False
                is_valid_value = False

        values.sort()

        return values

    def split_cmdline(self, cmdline):
        return [m.group(0) for m in self.CMDLINE_REGXP.finditer(cmdline)]

    def get_string_source(self):
        import os
        import platform

        # import pdb; pdb.set_trace()

        cmdline = None
        if platform.system() == 'Windows':
            # TODO use winapi to obtain the command line
            return ''
        elif platform.system() == 'Linux':
            # TODO try to use proc
            pass

        if cmdline is None and os.name == 'posix':
            from subprocess import CalledProcessError, check_output as spawn

            try:
                cmdline = spawn(['ps', '-ww', '-p', str(os.getpid()), '-o', 'command='])
            except CalledProcessError:
                return ''
        else:
            # current system doesn't have a way to get the command line
            return ''

        cmdline = cmdline.decode('utf-8').strip()
        cmdline = self.split_cmdline(cmdline)

        extra_args = sys.argv[1:]
        if len(extra_args) > 0:
            if cmdline[-len(extra_args):] != extra_args:
                # we can't rely on the output to be correct; fail!
                return ''

            cmdline = cmdline[1:-len(extra_args)]

        skip = 0
        for i in range(len(cmdline)):
            a = cmdline[i].strip()
            if not a.startswith('-c'):
                skip += 1
            else:
                a = a[2:].strip()
                if len(a) > 0:
                    cmdline[i] = a
                else:
                    skip += 1
                break

        cmdline = cmdline[skip:]
        source = ' '.join(cmdline)

        return source

    def get_traceback_information(self, tb):
        lineno = tb.tb_lineno
        filename = tb.tb_frame.f_code.co_filename
        function = tb.tb_frame.f_code.co_name

        repl = get_repl()
        if repl is not None and filename in repl.entries:
            _, filename, source = repl.entries[filename]
            source = source.replace('\r\n', '\n').split('\n')[lineno - 1]
        elif filename == '<string>':
            source = self.get_string_source()
        else:
            source = linecache.getline(filename, lineno)

        source = source.strip()

        relevant_values = self.get_relevant_values(source, tb.tb_frame)

        return filename, lineno, function, source, relevant_values


    def format_traceback_frame(self, tb):
        filename, lineno, function, source, relevant_values = self.get_traceback_information(tb)

        if self._colored:
            lineno = self._theme["lineno"].format(lineno)
            filename = self._colorize_filepath(filename)
            source = self._highlighter.highlight(source)
            if function:
                function = self._theme["function"].format(function)

        lines = [source]
        for i in reversed(range(len(relevant_values))):
            col, val = relevant_values[i]
            pipe_cols = [pcol for pcol, _ in relevant_values[:i]]
            pre_line = ''
            index = 0

            for pc in pipe_cols:
                pre_line += (' ' * (pc - index)) + self._pipe_char
                index = pc + 1

            pre_line += ' ' * (col - index)
            val_lines = val.split('\n')

            for n, val_line in enumerate(val_lines):
                if n == 0:
                    line = pre_line + self._cap_char + ' '
                else:
                    line = pre_line + ' ' * (len(self._cap_char) + 1)

                if self._colored:
                    line = self._theme["arrows"].format(line) + self._theme["value"].format(val_line)
                else:
                    line = line + val_line

                lines.append(line)

        formatted = '\n    '.join(lines)

        return (filename, lineno, function, formatted), source


    def format_traceback(self, tb=None):
        omit_last = False
        if not tb:
            try:
                raise Exception()
            except Exception:
                omit_last = True
                _, _, tb = sys.exc_info()
                assert tb is not None

        frames = []
        final_source = ""
        while tb:
            if omit_last and not tb.tb_next:
                break

            formatted, source = self.format_traceback_frame(tb)

            # special case to ignore runcode() here.
            if not (os.path.basename(formatted[0]) == 'code.py' and formatted[2] == 'runcode'):
                final_source = source
                frames.append(formatted)

            tb = tb.tb_next

        lines = traceback.format_list(frames)

        return ''.join(lines), final_source

    def _format_exception(self, value, tb, seen=None):
        # Implemented from built-in traceback module:
        # https://github.com/python/cpython/blob/a5b76167dedf4d15211a216c3ca7b98e3cec33b8/Lib/traceback.py#L468

        exc_type, exc_value, exc_traceback = type(value), value, tb

        if seen is None:
            seen = set()

        seen.add(id(exc_value))

        if exc_value:
            if exc_value.__cause__ is not None and id(exc_value.__cause__) not in seen:
                for text in self._format_exception(exc_value.__cause__,exc_value.__cause__.__traceback__, seen=seen):
                    yield text
                cause = "The above exception was the direct cause of the following exception:"
                if self._colored:
                    cause = self._theme["cause"].format(cause)
                yield "\n" + cause + "\n\n"
            elif exc_value.__context__ is not None and id(exc_value.__context__) not in seen and not exc_value.__suppress_context__:
                for text in self._format_exception(exc_value.__context__, exc_value.__context__.__traceback__, seen=seen):
                    yield text
                context = "During handling of the above exception, another exception occurred:"
                if self._colored:
                    context = self._theme["context"].format(context)
                yield "\n" + context + "\n\n"

        if exc_traceback is not None:
            introduction = "Traceback (most recent call last):"
            if self._colored:
                introduction = self._theme["introduction"].format(introduction)
            yield introduction + "\n"

        formatted, final_source = self.format_traceback(exc_traceback)

        yield formatted

        if not str(exc_value) and issubclass(exc_type, AssertionError):
            exc_value.args = (final_source,)

        exc = traceback.TracebackException(exc_type, exc_value, None)

        if self._colored and issubclass(exc_type, SyntaxError):
            exc.filename = self._colorize_filepath(exc.filename or "<string>")
            exc.lineno = self._theme["lineno"].format(exc.lineno or "?", "lineno")
            exc.text = self._highlighter.highlight(exc.text)

        title = list(exc.format_exception_only())

        if self._colored and title and ':' in title[-1]:
            exception_type, exception_value = title[-1].split(':', 1)
            exception_type = self._theme["exception_type"].format(exception_type)
            exception_value = self._theme["exception_value"].format(exception_value)
            title[-1] = exception_type + ":" + exception_value

        yield "".join(title)

    def format_exception(self, exc, value, tb):
        for line in self._format_exception(value, tb):
            yield line
