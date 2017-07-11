from collections import deque
from functools import singledispatch, partial, wraps
from time import time

import toolz
from tornado import gen
from tornado.locks import Condition
from tornado.ioloop import IOLoop
from tornado.queues import Queue


no_default = '--no-default--'


def identity(x):
    return x


class Stream(object):
    """ A Stream is an infinite sequence of data

    Streams subscribe to each other passing and transforming data between them.
    A Stream object listens for updates from upstream, reacts to these updates,
    and then emits more data to flow downstream to all Stream objects that
    subscribe to it.  Downstream Stream objects may connect at any point of a
    Stream graph to get a full view of the data coming off of that point to do
    with as they will.

    Examples
    --------
    >>> def inc(x):
    ...     return x + 1

    >>> source = Stream()  # Create a stream object
    >>> s = source.map(inc).map(str)  # Subscribe to make new streams
    >>> s.sink(print)  # take an action whenever an element reaches the end

    >>> L = list()
    >>> s.sink(L.append)  # or take multiple actions (streams can branch)

    >>> for i in range(5):
    ...     source.emit(i)  # push data in at the source
    '1'
    '2'
    '3'
    '4'
    '5'
    >>> L  # and the actions happen at the sinks
    ['1', '2', '3', '4', '5']
    """
    def __init__(self, child=None, children=None, **kwargs):
        self.parents = []
        if children is not None:
            self.children = children
        else:
            self.children = [child]
        if kwargs.get('loop'):
            self._loop = kwargs.get('loop')
        for child in self.children:
            if child:
                child.parents.append(self)

    def emit(self, x):
        """ Push data into the stream at this point

        This is typically done only at source Streams but can theortically be
        done at any point
        """
        result = []
        for parent in self.parents:
            r = parent.update(x, who=self)
            if type(r) is list:
                result.extend(r)
            else:
                result.append(r)
        return [element for element in result if element is not None]

    @property
    def child(self):
        if len(self.children) != 1:
            raise ValueError("Stream has multiple children")
        else:
            return self.children[0]

    @property
    def loop(self):
        try:
            return self._loop
        except AttributeError:
            pass
        for child in self.children:
            if child:
                loop = self.child.loop
                if loop:
                    self._loop = loop
                    return loop
        self._loop = IOLoop.current()
        return self._loop

    def map(self, func, *args, **kwargs):
        """ Apply a function to every element in the stream """
        return map(func, self, *args, **kwargs)

    # TODO : Make Stream inherit all this (function registry?)
    def select(self, *elems, **kwargs):
        """ Access the select attribute of the stream."""
        def select(obj, *elems):
            return obj.select(*elems, **kwargs)
        return map(select, self, *elems, raw=True, **kwargs)

    def filter(self, predicate):
        """ Only pass through elements that satisfy the predicate """
        return filter(predicate, self)

    def remove(self, predicate):
        """ Only pass through elements for which the predicate returns False
        """
        return filter(lambda x: not predicate(x), self)

    def accumulate(self, func, raw=False, start=no_default):
        """ Accumulate results with previous state

        This preforms running or cumulative reductions, applying the function
        to the previous total and the new element.  The function should take
        two arguments, the previous accumulated state and the next element and
        it should return a new accumulated state.

        Examples
        --------
        >>> source = Stream()
        >>> source.accumulate(lambda acc, x: acc + x).sink(print)
        ...
        >>> for i in range(5):
        ...     source.emit(i)
        1
        3
        6
        10
        15
        """
        return scan(func, self, raw=raw, start=start)

    scan = accumulate

    def partition(self, n):
        """ Partition stream into tuples of equal size

        Examples
        --------
        >>> source = Stream()
        >>> source.partition(3).sink(print)
        >>> for i in range(10):
        ...     source.emit(i)
        (0, 1, 2)
        (3, 4, 5)
        (6, 7, 8)
        """
        return partition(n, self)

    def sliding_window(self, n):
        """ Produce overlapping tuples of size n

        Examples
        --------
        >>> source = Stream()
        >>> source.sliding_window(3).sink(print)
        >>> for i in range(8):
        ...     source.emit(i)
        (0, 1, 2)
        (1, 2, 3)
        (2, 3, 4)
        (3, 4, 5)
        (4, 5, 6)
        (5, 6, 7)
        """
        return sliding_window(n, self)

    def rate_limit(self, interval):
        """ Limit the flow of data

        This stops two elements of streaming through in an interval shorter
        than the provided value.

        Parameters
        ----------
        interval: float
            Time in seconds
        """
        return rate_limit(interval, self)

    def buffer(self, n, loop=None):
        """ Allow results to pile up at this point in the stream

        This allows results to buffer in place at various points in the stream.
        This can help to smooth flow through the system when backpressure is
        applied.
        """
        return buffer(n, self, loop=loop)

    def timed_window(self, interval, loop=None):
        """ Emit a tuple of collected results every interval

        Every ``interval`` seconds this emits a tuple of all of the results
        seen so far.  This can help to batch data coming off of a high-volume
        stream.
        """
        return timed_window(interval, self, loop=loop)

    def delay(self, interval, loop=None):
        """ Add a time delay to results """
        return delay(interval, self, loop=None)

    def combine_latest(self, *others):
        """ Combine multiple streams together to a stream of tuples

        This will emit a new tuple of all of the most recent elements seen from
        any stream.
        """
        return combine_latest(self, *others)

    def concat(self):
        """ Flatten streams of lists or iterables into a stream of elements

        Examples
        --------
        >>> source = Stream()
        >>> source.concat().sink(print)
        >>> for x in [[1, 2, 3], [4, 5], [6, 7, 7]]:
        ...     source.emit(x)
        1
        2
        3
        4
        5
        6
        7
        """
        return concat(self)

    flatten = concat

    def union(self, *others):
        """ Combine multiple streams into one

        Every element from any of the children streams will immediately flow
        into the output stream.  They will not be combined with elements from
        other streams.

        See also
        --------
        Stream.zip
        Stream.combine_latest
        """
        return union(children=(self,) + others)

    def unique(self, history=None, key=identity):
        """ Avoid sending through repeated elements

        This deduplicates a stream so that only new elements pass through.
        You can control how much of a history is stored with the ``history=``
        parameter.  For example setting ``history=1`` avoids sending through
        elements when one is repeated right after the other.

        Examples
        --------
        >>> source = Stream()
        >>> source.unique(history=1).sink(print)
        >>> for x in [1, 1, 2, 2, 2, 1, 3]:
        ...     source.emit(x)
        1
        2
        1
        3
        """
        return unique(self, history=history, key=key)

    def collect(self, cache=None):
        """
        Hold elements in a cache and emit them as a collection when flushed.

        Examples
        --------
        >>> source1 = Stream()
        >>> source2 = Stream()
        >>> collector = collect(source1)
        >>> collector.sink(print)
        >>> source2.sink(collector.flush)
        >>> source1.emit(1)
        >>> source1.emit(2)
        >>> source2.emit('anything')  # flushes collector
        ...
        [1, 2]
        """
        return collect(self, cache=cache)

    def zip(self, *other):
        """ Combine two streams together into a stream of tuples """
        return zip(self, *other)

    # TODO : dispatch for zip
    def merge(self, *other):
        """ Merge streams together. This assumes streams are represented by
        dicts."""
        # print("in merge streams : {}".format(other))
        return merge(self, *other)

    def to_dask(self):
        """ Convert to a Dask Stream

        Operations like map and accumulate/scan on this stream will result in
        Future objects running on a cluster.  You should have already started a
        Dask Client running
        """
        from .dask import DaskStream
        return DaskStream(self)

    def sink(self, func):
        """ Apply a function on every element

        Examples
        --------
        >>> source = Stream()
        >>> L = list()
        >>> source.sink(L.append)
        >>> source.sink(print)
        >>> source.sink(print)
        >>> source.emit(123)
        123
        123
        >>> L
        [123]

        See Also
        --------
        Stream.sink_to_list
        """
        return Sink(func, self)

    def sink_to_list(self):
        """ Append all elements of a stream to a list as they come in

        Examples
        --------
        >>> source = Stream()
        >>> L = source.map(lambda x: 10 * x).sink_to_list()
        >>> for i in range(5):
        ...     source.emit(i)
        >>> L
        [0, 10, 20, 30, 40]
        """
        L = []
        Sink(L.append, self)
        return L

    def frequencies(self):
        """ Count occurrences of elements """
        def update_frequencies(last, x):
            return toolz.assoc(last, x, last.get(x, 0) + 1)

        return self.scan(update_frequencies, start={})


class Sink(Stream):
    def __init__(self, func, child):
        self.func = func

        Stream.__init__(self, child)

    def update(self, x, who=None):
        result = self.func(x)
        if type(result) is gen.Future:
            return result
        else:
            return []


@singledispatch
class map(Stream):
    def __init__(self, func, child, *args, raw=False, **kwargs):
        self.func = func
        self.kwargs = kwargs
        self.raw = raw
        self.args = args

        Stream.__init__(self, child)

    def update(self, x, who=None):
        if self.raw:
            return self.emit(self.func(x, *self.args, **self.kwargs))

        return self.emit(_stream_map(self.func, x, *self.args, **self.kwargs))


class filter(Stream):
    def __init__(self, predicate, child):
        self.predicate = predicate

        Stream.__init__(self, child)

    def update(self, x, who=None):
        if self.predicate(x):
            return self.emit(x)
        # else:
        # return self.emit(NOOP())


class scan(Stream):
    def __init__(self, func, child, raw=False, start=no_default):
        self.func = func
        self.raw = raw
        self.state = start
        Stream.__init__(self, child)

    def update(self, x, who=None):
        if self.raw:
            # prevstate, newstate
            result = self.func(self.state, x)
        else:
            result = _stream_accumulate(self.state, x, func=self.func)
        self.state = result

        # should return even on first element
        # (previous library waited before returning)
        return self.emit(result)


class partition(Stream):
    def __init__(self, n, child):
        self.n = n
        self.buffer = []
        Stream.__init__(self, child)

    def update(self, x, who=None):
        self.buffer.append(x)
        if len(self.buffer) == self.n:
            result, self.buffer = self.buffer, []
            return self.emit(tuple(result))
        else:
            return []


class sliding_window(Stream):
    def __init__(self, n, child):
        self.n = n
        self.buffer = deque(maxlen=n)
        Stream.__init__(self, child)

    def update(self, x, who=None):
        self.buffer.append(x)
        if len(self.buffer) == self.n:
            return self.emit(tuple(self.buffer))
        else:
            return []


class timed_window(Stream):
    def __init__(self, interval, child, loop=None):
        self.interval = interval
        self.buffer = []
        self.last = gen.moment

        Stream.__init__(self, child, loop=loop)

        self.loop.add_callback(self.cb)

    def update(self, x, who=None):
        self.buffer.append(x)
        return self.last

    @gen.coroutine
    def cb(self):
        while True:
            L, self.buffer = self.buffer, []
            self.last = self.emit(L)
            yield self.last
            yield gen.sleep(self.interval)


class delay(Stream):
    def __init__(self, interval, child, loop=None):
        self.interval = interval
        self.queue = Queue()

        Stream.__init__(self, child, loop=loop)

        self.loop.add_callback(self.cb)

    @gen.coroutine
    def cb(self):
        while True:
            last = time()
            x = yield self.queue.get()
            yield self.emit(x)
            duration = self.interval - (time() - last)
            if duration > 0:
                yield gen.sleep(duration)

    def update(self, x, who=None):
        return self.queue.put(x)


class rate_limit(Stream):
    def __init__(self, interval, child):
        self.interval = interval
        self.next = 0

        Stream.__init__(self, child)

    @gen.coroutine
    def update(self, x, who=None):
        now = time()
        old_next = self.next
        self.next = max(now, self.next) + self.interval
        if now < old_next:
            yield gen.sleep(old_next - now)
        yield self.emit(x)


class buffer(Stream):
    def __init__(self, n, child, loop=None):
        self.queue = Queue(maxsize=n)

        Stream.__init__(self, child, loop=loop)

        self.loop.add_callback(self.cb)

    def update(self, x, who=None):
        return self.queue.put(x)

    @gen.coroutine
    def cb(self):
        while True:
            x = yield self.queue.get()
            yield self.emit(x)


class zip(Stream):
    def __init__(self, *children, **kwargs):
        self.maxsize = kwargs.pop('maxsize', 10)
        self.buffers = [deque() for _ in children]
        self.condition = Condition()
        Stream.__init__(self, children=children)

    def update(self, x, who=None):
        L = self.buffers[self.children.index(who)]
        L.append(x)
        if len(L) == 1 and all(self.buffers):
            tup = tuple(buf.popleft() for buf in self.buffers)
            self.condition.notify_all()
            if tup and hasattr(tup[0], '__stream_merge__'):
                tup = tup[0].__stream_merge__(*tup[1:])
            return self.emit(tup)
        elif len(L) > self.maxsize:
            return self.condition.wait()


class merge(Stream):
    ''' This assumes that each stream is some kind of dictionary.
        Apply a rightermost update rule.

        This is same idea as zip except that rather than using tuples, we use
        dicts (and so hence there can be collisions in this case).
    '''
    def __init__(self, *children, **kwargs):
        self.maxsize = kwargs.pop('maxsize', 10)
        self.buffers = [deque() for _ in children]
        self.condition = Condition()
        Stream.__init__(self, children=children)

    def update(self, x, who=None):
        L = self.buffers[self.children.index(who)]
        L.append(x)
        if len(L) == 1 and all(self.buffers):
            # in case of delayed instance, this is necessary
            res = self.buffers[0].popleft()
            for buf in self.buffers[1:]:
                # this is meant to allow data that has a "merge" feature
                # TODO : to be improved (removed??)
                buftmp = buf.popleft()
                if hasattr(res, 'merge'):
                    # print("found merge attribute")
                    res = res.merge(buftmp)
                else:
                    # print("did not find merge attribute")
                    res.update(buftmp)
            self.condition.notify_all()
            return self.emit(res)
        elif len(L) > self.maxsize:
            return self.condition.wait()


class combine_latest(Stream):
    def __init__(self, *children):
        self.last = [None for _ in children]
        self.missing = set(children)
        Stream.__init__(self, children=children)

    def update(self, x, who=None):
        if self.missing and who in self.missing:
            self.missing.remove(who)

        self.last[self.children.index(who)] = x
        # only emit from the parent child
        if not self.missing and who == self.children[0]:
            tup = tuple(self.last)
            if tup and hasattr(tup[0], '__stream_merge__'):
                tup = tup[0].__stream_merge__(*tup[1:])
            return self.emit(tup)


class concat(Stream):
    def update(self, x, who=None):
        L = []
        for item in x:
            y = self.emit(item)
            if type(y) is list:
                L.extend(y)
            else:
                L.append(y)
        return L


class unique(Stream):
    def __init__(self, child, history=None, key=identity):
        self.seen = dict()
        self.key = key
        if history:
            from zict import LRU
            self.seen = LRU(history, self.seen)

        Stream.__init__(self, child)

    def update(self, x, who=None):
        y = self.key(x)
        if y not in self.seen:
            self.seen[y] = 1
            return self.emit(x)


class union(Stream):
    def update(self, x, who=None):
        return self.emit(x)


class collect(Stream):
    def __init__(self, child, cache=None):
        if cache is None:
            cache = deque()
        self.cache = cache

        Stream.__init__(self, child)

    def update(self, x, who=None):
        self.cache.append(x)

    def flush(self, _=None):
        out = tuple(self.cache)
        self.emit(out)
        self.cache.clear()


# dispatch on first arg
# another option is to supply a wrapper function
def _stream_map(func, *args, **kwargs):
    '''
    dispatch is performed on first argument (args[0])

    if no arugments, make a placeholder object
    (which will default computation to be run to base)

    The issue with this is that we do want to allow one object to eventually
    spread into args/kwargs...
    There doesn't seem to be a clean way around this...
    User could also add their own wrapper functions, but we add this
    convenience to allow for shorter code. (since it happens quite often)
    '''
    if len(args) > 0:
        obj = args[0]
    else:
        obj = object()

    # assume map is done on first arg only
    sm = stream_map.dispatch(type(obj))
    if sm is base_stream_map:
        # run on args instead
        # print("in base stream map, obj : {}".format(obj))
        return func(*args, **kwargs)
    else:
        # assume map is done on first arg only
        return sm(wraps(func)(partial(_stream_map, func)), *args, **kwargs)


def _stream_accumulate(prevobj, nextobj, func=None, **kwargs):
    '''
        Stream accumulate is simpler. We enforce the requirement that a
        function must behave as f(prev, next). User has to write their own
        wrapper functions.

        Needs to handle an initialization case when first object is None.

        Dispatch is done on prevobj
    '''

    sm = stream_accumulate.dispatch(type(prevobj))

    if prevobj is no_default:
        return nextobj
    else:
        if sm is base_stream_accumulate:
            return func(prevobj, nextobj, **kwargs)
        else:
            return sm(prevobj, nextobj, wraps(func)(partial(_stream_accumulate,
                                                            func=func,
                                                            **kwargs)))


@singledispatch
def stream_map(func, *args, **kwargs):
    return func(*args, **kwargs)

base_stream_map = stream_map.dispatch(object)


# TODO : stream_accumulate should also keep internal state
@singledispatch
def stream_accumulate(prevobj, nextobj, func):
    result = func(prevobj, nextobj)
    return result

base_stream_accumulate = stream_accumulate.dispatch(object)

# for control statements
# class NOOP:
# pass

# @stream_map.register(NOOP)
# def _(*args, **kwargs):
# return NOOP()
