"""Handy utility functions."""

import base64
import contextlib
import functools
import logging
import os
import pkgutil
import platform
import sys
import tkinter as tk

log = logging.getLogger(__name__)


class CallbackHook:
    """Simple object that runs callbacks.

    >>> hook = CallbackHook('whatever')
    >>> @hook.connect
    ... def user_callback(value):
    ...     print("user_callback called with", value)
    ...
    >>> hook.run(123)       # usually porcupine does this
    user_callback called with 123

    You can hook multiple callbacks too:

    >>> @hook.connect
    ... def another_callback(value):
    ...     print("another_callback called with", value)
    ...
    >>> hook.run(456)
    user_callback called with 456
    another_callback called with 456

    Callback hooks have a ``callbacks`` attribute that contains a list
    of hooked functions. It's useful for things like checking if a
    callback has been connected.

    >>> hook.callbacks == [user_callback, another_callback]
    True

    Errors in the connected functions will be logged to
    ``logging.getLogger(logname)``. The *unhandled_errors* argument
    should be an iterable of exceptions that won't be handled.
    """

    def __init__(self, logname, *, unhandled_errors=()):
        self._log = logging.getLogger(logname)
        self._unhandled = tuple(unhandled_errors)  # isinstance() likes tuples
        self._blocklevel = 0
        self.callbacks = []

    def connect(self, function):
        """Schedule a function to be called when the hook is ran.

        The function is returned too, so this can be used as a
        decorator.
        """
        self.callbacks.append(function)
        return function

    def disconnect(self, function):
        """Undo a :meth:`connect` call."""
        self.callbacks.remove(function)

    # TODO: get rid of this? i originally added this to help with
    # garbage collection but it's not really an issue anyway
    def disconnect_all(self):
        """Disconnect all connected callbacks.

        This should be ran when the hook won't be needed anymore.
        """
        self.callbacks.clear()

    @contextlib.contextmanager
    def blocked(self):
        """Prevent the callbacks from running temporarily.

        Use this as a context manager, like this::

            with some_hook.blocked():
                # do something that would normally run the callbacks
        """
        self._blocklevel += 1
        try:
            yield
        finally:
            self._blocklevel -= 1

    def is_blocked(self):
        """Return True if :meth:`~blocked` is running somewhere."""
        assert self._blocklevel >= 0
        return self._blocklevel > 0

    def _handle_error(self, callback, error):
        if isinstance(error, self._unhandled):
            raise error
        self._log.exception("%s doesn't work", nice_repr(callback))

    def run(self, *args):
        """Run ``callback(*args)`` for each connected callback.

        This does nothing if :meth:`~blocked` is currently running.
        """
        if not self.is_blocked():
            for callback in self.callbacks:
                try:
                    callback(*args)
                except Exception as e:
                    self._handle_error(callback, e)


class ContextManagerHook(CallbackHook):
    """A :class:`.CallbackHook` subclass for "set up and tear down" callbacks.

    The connected callbacks should usually do something, yield and then
    undo everything they did, just like :func:`contextlib.contextmanager`
    functions.

    >>> hook = ContextManagerHook('whatever')
    >>> @hook.connect
    ... def hooked_callback():
    ...     print("setting up")
    ...     yield
    ...     print("tearing down")
    ...
    >>> with hook.run():
    ...     print("now things are set up")
    ...
    setting up
    now things are set up
    tearing down
    >>>
    """

    @contextlib.contextmanager
    def run(self, *args):
        """Run ``callback(*args)`` for each connected callback.

        This does nothing if :meth:`~blocked` is currently running.
        """
        if self.is_blocked():
            return

        generators = []   # [(callback, generator), ...]
        for callback in self.callbacks:
            try:
                generator = callback(*args)
                if not hasattr(type(generator), '__next__'):
                    raise RuntimeError("the function didn't yield")
                next(generator)
                generators.append((callback, generator))
            except Exception as e:
                self._handle_error(callback, e)

        yield

        for callback, generator in generators:
            try:
                next(generator)     # should raise StopIteration
                raise RuntimeError("the function yieleded twice")
            except StopIteration:
                pass
            except Exception as e:
                self._handle_error(callback, e)


@functools.lru_cache()
def running_pythonw():
    """Return True if Porcupine is running in pythonw.exe on Windows."""
    if platform.system() != 'Windows':
        return False
    return os.path.basename(sys.executable).lower() == 'pythonw.exe'


@functools.lru_cache()
def get_image(filename):
    """Create a tkinter PhotoImage from a file in porcupine/images.

    This function is cached and the cache holds references to all
    returned images, so there's no need to worry about calling this
    function too many times or keeping reference to the returned images.

    Only gif images should be added to porcupine/images. Other image
    formats don't work with old Tk versions.
    """
    data = pkgutil.get_data('porcupine', 'images/' + filename)
    return tk.PhotoImage(format='gif', data=base64.b64encode(data))


def get_root():
    """Return tkinter's current root window."""
    # tkinter's default root window is not accessible as a part of the
    # public API, but tkinter uses _default_root everywhere so I don't
    # think it's going away
    return tk._default_root


def get_window(widget):
    """Return the tk.Tk or tk.Toplevel widget that a widget is in."""
    while not isinstance(widget, (tk.Tk, tk.Toplevel)):
        widget = widget.master
    return widget


def errordialog(title, message, plaintext=None):
    """Like messagebox.showinfo, but supports plain text messages.

    If plaintext is not None, it will be displayed below the message in
    a tkinter text widget.
    """
    if tk._default_root is None:
        # create new main window
        window = tk.Tk()
    else:
        window = tk.Toplevel()
        window.transient(tk._default_root)

    label = tk.Label(window, text=message, height=5)

    if plaintext is None:
        label.pack(fill='both', expand=True)
        geometry = '250x150'
    else:
        label.pack(anchor='center')
        text = tk.Text(window, width=1, height=1)
        text.pack(fill='both', expand=True)
        text.insert('1.0', plaintext)
        text['state'] = 'disabled'
        geometry = '400x300'

    button = tk.Button(text="OK", width=6, command=window.destroy)
    button.pack(pady=10)

    window.title(title)
    window.geometry(geometry)
    window.wait_window()


def bind_mouse_wheel(widget, callback, *, prefixes='', **kwargs):
    """Bind mouse wheel events to callback.

    The callback will be called like callback(direction) where direction
    is 'up' or 'down'. The prefixes argument can be used to change the
    binding string. For example, prefixes='Control-' means that callback
    will be ran when the user holds down Control and rolls the wheel.
    """
    # i needed to cheat and use stackoverflow, the man pages don't say
    # what OSX does with MouseWheel events and i don't have an
    # up-to-date OSX :( the non-x11 code should work on windows and osx
    # http://stackoverflow.com/a/17457843
    if get_root().tk.call('tk', 'windowingsystem') == 'x11':
        def real_callback(event):
            callback('up' if event.num == 4 else 'down')

        widget.bind('<{}Button-4>'.format(prefixes), real_callback, **kwargs)
        widget.bind('<{}Button-5>'.format(prefixes), real_callback, **kwargs)

    else:
        def real_callback(event):
            callback('up' if event.delta > 0 else 'down')

        widget.bind('<{}MouseWheel>'.format(prefixes),
                    real_callback, **kwargs)


def nice_repr(obj):
    """Return a nice string representation of an object.

    >>> import time
    >>> nice_repr(time.strftime)
    'time.strftime'
    >>> nice_repr(object())     # doctest: +ELLIPSIS
    '<object object at 0x...>'
    """
    try:
        return obj.__module__ + '.' + obj.__qualname__
    except AttributeError:
        return repr(obj)


class Checkbox(tk.Checkbutton):
    """Like tk.Checkbutton, but works with my dark GTK+ theme."""
    # tk.Checkbutton displays a white checkmark on a white background to
    # me, and changing the checkmark color also changes the text color

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print('aaa', self['highlightcolor'], self['foreground'])
        if self['selectcolor'] == self['foreground'] == '#ffffff':
            print('lulz', self['background'])
            self['selectcolor'] = self['background']


if __name__ == '__main__':
    import doctest
    print(doctest.testmod())
