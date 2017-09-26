"""Beautiful and helpful exceptions

User can `import better_exceptions_core` to use functions without any side effects.


   Name: better_exceptions
 Author: Josh Junon
  Email: josh@junon.me
    URL: github.com/qix-/better-exceptions
License: Copyright (c) 2017 Josh Junon, licensed under the MIT license
"""

from __future__ import absolute_import

import inspect
import linecache
import os
import re
import sys
import traceback

import ansimarkup
from pygments.token import Token

from .color import SUPPORTS_COLOR
from .highlighter import Highlighter
from .repl import get_repl


PY3 = sys.version_info[0] >= 3

THEME = {
    'introduction': u'<r>{introduction}</r>',
    'cause': u'<b>{cause}</b>',
    'context': u'<b>{context}</b>',
    'location': u'File "<g>{dirname}{basename}</g>", line <y>{lineno}</y>, in <m>{source}</m>',
    'short_location': u'File "<g>{dirname}{basename}</g>", line <y>{lineno}</y>',
    'exception': u'<lr>{type}</lr>:<b>{value}</b>',
    'pipe': u'<c>{pipe}</c>',
    'cap': u'<c>{cap}</c>',
    'value': u'<c><b>{value}</b></c>',
}

MAX_LENGTH = 128


class ExceptionFormatter(object):

    CMDLINE_REGXP = re.compile(r'(?:[^\t ]*([\'"])(?:\\.|.)*(?:\1))[^\t ]*|([^\t ]+)')
    LOCATION_REGXP = re.compile(r'^  File "(?P<filepath>.*?)", line (?P<lineno>(?:\d+|\?)), in (?P<source>.*)$', flags=re.M)
    SHORT_LOCATION_REGXP = re.compile(r'^  File "(?P<filepath>.*?)", line (?P<lineno>(?:\d+|\?))$', flags=re.M)
    EXCEPTION_REGXP = re.compile(r'^(?P<type>.+?):(?P<value>.*)$')

    def __init__(self, colored=SUPPORTS_COLOR, theme=THEME, max_length=MAX_LENGTH, encoding=None):
        self._colored = colored
        self._theme = theme
        self._max_length = max_length
        self._encoding = encoding or 'ascii'
        self._pipe_char = self.get_pipe_char()
        self._cap_char =  self.get_cap_char()
        self._introduction = u'Traceback (most recent call last):'
        self._cause = getattr(traceback, '_cause_message', u"The above exception was the direct cause of the following exception:").strip()
        self._context = getattr(traceback, '_context_message', u"During handling of the above exception, another exception occurred:").strip()
        self._highlighter = Highlighter()

    def _get_char(self, value, default):
        try:
            value.encode(self._encoding)
        except UnicodeEncodeError:
            return default
        else:
            return value

    def get_pipe_char(self):
        return self._get_char(u'\u2502', u'|')

    def get_cap_char(self):
        return self._get_char(u'\u2514', u'->')

    def get_relevant_names(self, source):
        source = source.encode(self._encoding, errors='backslashreplace')
        source = source.decode(self._encoding)
        tokens = self._highlighter.get_tokens(source)
        return [token for token in tokens if token[1] in Token.Name]

    def format_value(self, v):
        try:
            v = repr(v)
        except:
            v = u'<unprintable %s object>' % type(v).__name__

        max_length = self._max_length
        if max_length is not None and len(v) > max_length:
            v = v[:max_length] + u'...'
        return v

    def get_relevant_values(self, source, frame):
        names = self.get_relevant_names(source)
        values = []

        for name in names:
            index, tokentype, value = name
            if value in frame.f_locals:
                val = frame.f_locals.get(value, None)
                values.append((value, index, self.format_value(val)))
            elif value in frame.f_globals:
                val = frame.f_globals.get(value, None)
                values.append((value, index, self.format_value(val)))

        values.sort(key=lambda e: e[1])
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
            return u''
        elif platform.system() == 'Linux':
            # TODO try to use proc
            pass

        if cmdline is None and os.name == 'posix':
            from subprocess import CalledProcessError, check_output as spawn

            try:
                cmdline = spawn(['ps', '-ww', '-p', str(os.getpid()), '-o', 'command='])
            except CalledProcessError:
                return u''

            if (PY3 and isinstance(cmdline, bytes)) or (not PY3 and isinstance(cmdline, str)):
                cmdline = cmdline.decode(sys.stdout.encoding or 'utf-8')
        else:
            # current system doesn't have a way to get the command line
            return u''

        cmdline = cmdline.strip()
        cmdline = self.split_cmdline(cmdline)

        extra_args = sys.argv[1:]
        if len(extra_args) > 0:
            if cmdline[-len(extra_args):] != extra_args:
                # we can't rely on the output to be correct; fail!
                return u''

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
        source = u' '.join(cmdline)

        return source

    def colorize(self, theme, **kwargs):
        template = self._theme[theme]
        if not self._colored:
            template = ansimarkup.strip(template)
        else:
            template = ansimarkup.parse(template)

        return template.format(**kwargs)

    def colorize_location(self, filepath, lineno, source=None):
        dirname, basename = os.path.split(filepath)
        if dirname:
            dirname += os.sep

        if source is None:
            theme = 'short_location'
        else:
            theme = 'location'

        return self.colorize(theme, dirname=dirname, basename=basename, lineno=lineno, source=source)

    def colorize_source(self, source):
        if not self._colored:
            return source
        return self._highlighter.highlight(source)

    def get_traceback_information(self, tb):
        frame_info = inspect.getframeinfo(tb)
        filename = frame_info.filename
        lineno = frame_info.lineno
        function = frame_info.function

        repl = get_repl()
        if repl is not None and filename in repl.entries:
            _, filename, source = repl.entries[filename]
            source = source.replace('\r\n', '\n').split('\n')[lineno - 1]
        elif filename == '<string>':
            source = self.get_string_source()
        else:
            source = linecache.getline(filename, lineno)
            if not PY3 and isinstance(source, str):
                source = source.decode('utf-8')

        source = source.strip()

        color_source = self.colorize_source(source)

        relevant_values = self.get_relevant_values(source, tb.tb_frame)

        return filename, lineno, function, source, color_source, relevant_values

    def format_traceback_frame(self, tb):
        filename, lineno, function, source, color_source, relevant_values = self.get_traceback_information(tb)

        lines = [color_source]
        for i in reversed(range(len(relevant_values))):
            _, col, val = relevant_values[i]
            pipe_cols = [pcol for _, pcol, _ in relevant_values[:i]]
            line = u''
            index = 0

            pipe = self.colorize('pipe', pipe=self._pipe_char)
            cap = self.colorize('cap', cap=self._cap_char)
            value = self.colorize('value', value=val)

            for pc in pipe_cols:
                line += (u' ' * (pc - index)) + pipe
                index = pc + 1

            line += u'{}{} {}'.format((u' ' * (col - index)), cap, value)
            lines.append(line)

        formatted = u'\n    '.join(lines)

        return (filename, lineno, function, formatted), color_source

    def format_traceback(self, tb=None):
        omit_last = False
        if not tb:
            try:
                raise Exception()
            except:
                omit_last = True
                _, _, tb = sys.exc_info()
                assert tb is not None

        frames = []
        final_source = u''
        while tb:
            if omit_last and not tb.tb_next:
                break

            formatted, colored = self.format_traceback_frame(tb)

            # special case to ignore runcode() here.
            if not (os.path.basename(formatted[0]) == 'code.py' and formatted[2] == 'runcode'):
                final_source = colored
                frames.append(formatted)

            tb = tb.tb_next

        lines = traceback.format_list(frames)
        new_lines = []

        for line in lines:
            colorize = lambda m: u'  ' + self.colorize_location(**m.groupdict())
            line = self.LOCATION_REGXP.sub(colorize, line)
            line = self.SHORT_LOCATION_REGXP.sub(colorize, line)
            new_lines.append(line)

        return u''.join(new_lines), final_source

    def sanitize(self, string):
        encoding = self._encoding
        return string.encode(encoding, errors='backslashreplace').decode(encoding)

    def format_exception(self, exc, value, tb, _seen=None):
        if _seen is None:
            _seen = {None}

        _seen.add(value)

        if value:
            if getattr(value, '__cause__', None) not in _seen:
                for text in self.format_exception(type(value.__cause__),
                                                  value.__cause__,
                                                  value.__cause__.__traceback__,
                                                  _seen=_seen):
                    yield text
                yield u'\n' + self.colorize('cause', cause=self._cause) + u'\n\n'
            elif getattr(value, '__context__', None) not in _seen and not getattr(value, '__suppress_context__', True):
                for text in self.format_exception(type(value.__context__),
                                                  value.__context__,
                                                  value.__context__.__traceback__,
                                                  _seen=_seen):
                    yield text
                yield u'\n' + self.colorize('context', context=self._context) + u'\n\n'

        formatted, colored_source = self.format_traceback(tb)

        if not str(value) and exc is AssertionError:
            value.args = (colored_source,)
        title = traceback.format_exception_only(exc, value)

        formatted_title = []


        for line in title:
            if line.startswith('    '):
                line = self.colorize_source(line) + u'\n'
            elif self.EXCEPTION_REGXP.match(line):
                match = self.EXCEPTION_REGXP.match(line)
                line = self.colorize('exception', **match.groupdict()) + u'\n'
            elif self.LOCATION_REGXP.match(line):
                match = self.LOCATION_REGXP.match(line)
                line = u'  ' + self.colorize_location(**match.groupdict()) + u'\n'
            elif self.SHORT_LOCATION_REGXP.match(line):
                match = self.SHORT_LOCATION_REGXP.match(line)
                line = u'  ' + self.colorize_location(**match.groupdict()) + u'\n'
            formatted_title.append(line)
        formatted_title = u''.join(formatted_title)

        yield self.colorize('introduction', introduction=self._introduction) + u'\n'

        yield self.sanitize(formatted)

        yield self.sanitize(formatted_title)
