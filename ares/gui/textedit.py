# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""A Text widget that reports every change of its text and every cursor move.

Every change passes through the widget command, whoever makes it: typing,
paste, cut, code, and undo and redo, which Tk applies by calling the widget
command by its path name. So Tk's widget command is hidden, keeping its
name for Tk's error messages, and a dispatcher takes the name in its place.

The functions after the widget help code that edits any Text widget: one
undo step, and the tags on newlines, which mark whole lines.
"""

import tkinter as tk
from contextlib import contextmanager

# The dispatcher is Tcl, not Python: an error raised out of a Python command
# also makes mainloop() raise it later, and failing commands are normal (Tk's
# paste binding tries "delete sel.first sel.last" and catches the error).
# Subcommands may be abbreviated, as Tk allows. insert, delete and replace
# run between two Python callbacks, and mark set insert is followed by one.
# Every other command is a tail call, which runs it in the caller's frame,
# as "search -count varName" needs.
_DISPATCH = """{path before after moved args} {
    set command [tcl::prefix match -error {} {bbox cget compare configure count debug
        delete dlineinfo dump edit get image index insert mark peer pendingsync replace
        scan search see sync tag window xview yview} [lindex $args 0]]
    switch -exact -- $command {
        insert - delete - replace {
            set change [$before $command {*}[lrange $args 1 end]]
            if {$command ne "delete"} {
                set pieces [lrange $args [expr {$command eq "insert" ? 2 : 3}] end]
                if {$change ne ""} {
                    # Tk inserts each piece of text before it reads the tag list
                    # after it: a malformed list must fail before anything changes.
                    foreach {chars tags} $pieces {
                        llength $tags
                    }
                }
                # Text without a tag list would take the tags on both sides of it.
                if {[llength $pieces] % 2} {
                    lappend args {}
                }
            }
            set result [interp invokehidden {} $path {*}$args]
            $after $change
            return $result
        }
        mark {
            set result [interp invokehidden {} $path {*}$args]
            lassign $args - option name
            # Tk has accepted the option, so a prefix of "set" is set.
            if {$name eq "insert" && [tcl::prefix match -error {} set $option] eq "set"} {
                $moved
            }
            return $result
        }
    }
    tailcall interp invokehidden {} $path {*}$args
}"""

# Tk deletes its command with the window, however the window is destroyed;
# a trace on it then removes the dispatcher and the Python callbacks.
_REMOVE = "{commands args} {foreach command $commands {rename $command {}}}"


class TrackedText(tk.Text):
    """Text that calls listeners after each change of its text and each cursor move.

    A change listener gets (first, removed, added): lines first ..
    first+removed-1 of the text before the change (numbered from 1) were
    replaced by lines first .. first+added-1 of the text after it. Cursor
    listeners run after the insert mark is set and after every change.
    Listeners run in the order they were added, once Tk has made the change;
    a command that fails changes nothing and reports nothing. Listeners must
    not change the text. An exception in a listener is reported like that of
    any Tk callback, and the other listeners still run.

    New text gets only the tags its command names: Tk would give text
    inserted without a tag list the tags on both sides of it, so text typed
    or pasted beside a marked line would be marked too. Tags on a line's
    newline mark the whole line (line_tags()), but Tk leaves them on the
    newline wherever it goes. A change that starts inside a line, ends at
    the end of a line and adds or removes line breaks (Enter or a paste at
    the end of a line, a deletion from inside a line to the end of a later
    one) leaves the newline after it at the end of another line than its
    own. So that newline loses its tags, and the newline that then ends the
    line where the change starts gets that line's.
    """

    def __init__(self, master=None, **options):
        super().__init__(master, **options)
        self._change_listeners = []
        self._cursor_listeners = []
        self._kept = None               # from _before_change to _after_change
        self.line_marks = ()            # tags that mark a whole line wherever they are on it
        # The trace removes the callbacks, so tkinter's destroy() must not.
        commands = (self._w, *(self.register(callback, needcleanup=False) for callback in
                               (self._before_change, self._after_change, self._cursor_moved)))
        self.tk.call("trace", "add", "command", self._w, "delete", ("apply", _REMOVE, commands))
        self.tk.call("interp", "hide", "", self._w)
        self.tk.call("interp", "alias", "", self._w, "", "apply", _DISPATCH, *commands)

    def add_change_listener(self, callback):
        """Call callback(first, removed, added) after every change of the text."""
        self._change_listeners.append(callback)

    def add_cursor_listener(self, callback):
        """Call callback() after every move of the insert mark."""
        self._cursor_listeners.append(callback)

    def line_count(self):
        """The number of lines; an empty text has one."""
        return self._position("end-1c")[0]

    def _position(self, index):
        """(line, column) of an index."""
        line, _, column = self.index(index).partition(".")
        return int(line), int(column)

    def _before_change(self, operation, *args):
        """The lines a change will touch, as "first last count", worked out before Tk makes it.

        Empty when the command changes nothing or fails before it changes
        anything. The line tags to keep with their line go to _kept.
        """
        self._kept = None
        if operation == "insert":
            indices, pieces = args[:1], args[1::2]
        elif operation == "replace":
            indices, pieces = args[:2], args[2::2]
        else:
            indices, pieces = args, ()
        try:
            if not indices or str(self.cget("state")) == "disabled":
                return ""
            positions = [self._position(index) for index in indices]
            if operation == "delete" and len(positions) % 2:
                # An index without a partner deletes one character, maybe a newline.
                positions.append(self._position("{}.{}+1c".format(*positions[-1])))
            count = self.line_count()
        except tk.TclError:
            return ""           # the command fails as well, with Tk's own message
        if operation == "replace" and positions[0] > positions[1]:
            return ""           # so does a replace of a backward range
        (first, column), last = min(positions), max(positions)[0]
        if last > count:
            # "end" lies after the final newline, which Tk never deletes. Text
            # goes in before that newline, and a deletion from the start of a
            # line up to "end" takes the newline before the line instead.
            last = count
            if operation == "insert":
                first = count
            elif column == 0:
                first = max(1, first - 1)
        if operation != "delete" or len(positions) == 2:
            self._kept = self._line_tags_kept(positions[0], positions[-1], count,
                                              sum(piece.count("\n") for piece in pieces))
        return f"{first} {last} {count}"

    def _line_tags_kept(self, start, stop, count, newlines):
        """What _after_change does to keep line tags with their lines, or None.

        The change starts at start and the old text after it at stop (as
        they are before it); the new text has newlines. Returns (line, its
        tags, the newline after the change once it is made, that one's tags).
        """
        # "end" stands for its newline, which Tk keeps: the end of the last line.
        (line, column), after = (self._position("end-1c") if position[0] > count else position
                                 for position in (start, stop))
        if not column or not (newlines or line < after[0]) \
                or after != self._position(f"{after[0]}.end"):
            return None
        return line, line_tags(self, line), f"{line + newlines}.end", line_tags(self, after[0])

    def _after_change(self, change):
        if not change:
            return
        if self._kept is not None:
            line, tags, newline, its_tags = self._kept
            for tag in its_tags:
                self.tag_remove(tag, newline)
            for tag in tags:
                self.tag_add(tag, f"{line}.end")
        first, last, count = map(int, change.split())
        removed = last - first + 1
        added = removed + self.line_count() - count
        self._notify(self._change_listeners, first, removed, added)
        self._cursor_moved()

    def _cursor_moved(self):
        self._notify(self._cursor_listeners)

    def _notify(self, listeners, *args):
        """Call every listener; one that raises is reported, and the others still run."""
        for listener in listeners:
            try:
                listener(*args)
            except Exception:
                self._report_exception()


def line_tags(text, line):
    """The tags that mark a whole line: those on its newline apart from sel, and the
    text's line_marks wherever they are on the line (joining two lines, or splitting
    one, leaves such a mark on part of a line)."""
    tags = set(text.tag_names(f"{line}.end")) - {"sel"}
    for tag in getattr(text, "line_marks", ()):
        if tag not in tags:
            # The last range to start before the newline; it may start on a line above.
            found = text.tag_prevrange(tag, f"{line}.end")
            if found and text.compare(found[1], ">", f"{line}.0"):
                tags.add(tag)
    return tags


def put_back_line_tags(text, first, last, tags):
    """Give lines first..last the line tags of tags, [(line, line tags)], after an edit.

    Each of those tags goes on the whole of each line listed with it, newline
    included, and comes off the rest of lines first..last.
    """
    for tag in set().union(*(names for _, names in tags)):
        text.tag_remove(tag, f"{first}.0", f"{last}.end +1c")
        text.tag_add(tag, *[index for line, names in tags if tag in names
                            for index in (f"{line}.0", f"{line}.end +1c")])


@contextmanager
def one_undo_step(text):
    """Make the edits in the with block one undo step, apart from the edits around it."""
    autoseparators = text.cget("autoseparators")
    text.edit_separator()
    text.configure(autoseparators=False)
    try:
        yield
    finally:
        text.configure(autoseparators=autoseparators)
        text.edit_separator()
