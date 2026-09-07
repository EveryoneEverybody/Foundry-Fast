"""Bounded console diagnostics and measured scenario phases, without bpy."""
from collections import Counter
from contextlib import contextmanager
from functools import wraps
from time import perf_counter


CAPABILITIES = ('Experimental reconstruction', 'All decoded permutations', 'Animations, gameplay',
                'Render topology', 'Blender material previews', 'Reference Only', 'Materials are placeholders',
                'No explicit model variant')


def category(reason):
    if reason.startswith(CAPABILITIES): return 'capability'
    text = reason.lower()
    for key, words in (
        ('reference_frame', ('reference frame',)), ('stored_pose', ('stored pose', 'node pose')),
        ('attachment', ('attachment', 'child object', 'parent/marker')),
        ('missing_dependency', ('missing dependency', 'cannot find', 'no such file', 'unavailable', 'missing source')),
        ('variant', ('variant', 'permutation', 'damage/state')),
        ('material', ('shader', 'bitmap', 'texture', 'material')),
        ('hierarchy', ('hierarchy', 'skin', 'bone', 'weight'))):
        if any(word in text for word in words): return key
    return 'source_specific'


def summarize(records, examples=3):
    groups = {}
    for row in records:
        key = category(row['reason'])
        group = groups.setdefault(key, dict(category=key, count=0, examples=[], unique_reasons=set()))
        group['count'] += 1
        if row['reason'] not in group['unique_reasons'] and len(group['examples']) < examples:
            group['examples'].append(dict(row))
        group['unique_reasons'].add(row['reason'])
    for group in groups.values(): group['unique_reasons'] = len(group['unique_reasons'])
    return list(groups.values())


def messages(summary):
    for group in summary:
        yield f"H3 {group['category']}: {group['count']} occurrences, {group['unique_reasons']} distinct reasons"
        for row in group['examples']:
            yield f"  {row.get('source_tag') or row.get('address', '')}: {row['reason']}"


class Profile:
    def __init__(self, clock=perf_counter):
        self.clock = clock
        self.rows = {}
        self.stack = []
        self.counts = Counter()

    @contextmanager
    def span(self, name):
        frame = [self.clock(), 0.]
        self.stack.append(frame)
        try: yield
        finally:
            elapsed = self.clock() - frame[0]
            self.stack.pop()
            if self.stack: self.stack[-1][1] += elapsed
            row = self.rows.setdefault(name, dict(calls=0, inclusive_seconds=0., exclusive_seconds=0.))
            row['calls'] += 1
            row['inclusive_seconds'] += elapsed
            row['exclusive_seconds'] += max(0., elapsed-frame[1])

    def steps(self, name, generator):
        try:
            while True:
                try:
                    with self.span(name): value = next(generator)
                except StopIteration as done: return done.value
                yield value
        finally: generator.close()

    def report(self):
        return dict(timings=self.rows, counts=dict(self.counts),
                    timing_semantics='Measured wall seconds inside phase calls. Generator suspension excluded; helper polling wait remains in extraction wall time. Nested phase time excluded from exclusive seconds. Unmeasured stages are absent, never zero estimates.')

    def elapsed(self, name, seconds):
        self.rows[name] = dict(calls=1, inclusive_seconds=seconds, exclusive_seconds=seconds)


def measured(name):
    def decorate(function):
        @wraps(function)
        def wrapped(self, *args, **kwargs):
            with self.profile.span(name): return function(self, *args, **kwargs)
        return wrapped
    return decorate
