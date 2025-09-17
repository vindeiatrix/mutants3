from src.mutants.repl.dispatch import Dispatch


class FakeBus:
    def __init__(self):
        self.events = []
    def push(self, kind, text, **_):
        self.events.append((kind, text))


def _dispatch():
    d = Dispatch()
    d.set_feedback_bus(FakeBus())
    return d


def test_unique_prefix_resolves():
    d = _dispatch()
    called = {}
    def inv(arg):
        called['ok'] = True
    d.register('inventory', inv)
    d.call('inv', '')
    assert called.get('ok') is True


def test_short_non_alias_warns():
    d = _dispatch()
    d.register('look', lambda arg: None)
    d.call('lo', '')
    assert d._bus.events == [
        ('SYSTEM/WARN', 'Unknown command "lo" (commands require at least 3 letters).')
    ]


def test_single_letter_alias_north_ok():
    d = _dispatch()
    called = {}
    def north(arg):
        called['dir'] = 'north'
    d.register('north', north)
    d.alias('n', 'north')
    d.call('n', '')
    assert called.get('dir') == 'north'


def test_call_returns_canonical_name():
    d = _dispatch()
    d.register('north', lambda arg: None)
    d.alias('n', 'north')
    assert d.call('n', '') == 'north'


def test_ambiguous_prefix_warns():
    d = _dispatch()
    d.register('drink', lambda arg: None)
    d.register('drive', lambda arg: None)
    d.call('dri', '')
    assert d._bus.events == [
        ('SYSTEM/WARN', 'Ambiguous command "dri" (did you mean: drink, drive)')
    ]


def test_direction_prefix_without_alias():
    d = _dispatch()
    called = {}

    def west(arg):
        called['dir'] = 'west'

    d.register('west', west)
    d.call('we', '')
    assert called.get('dir') == 'west'
    assert d._bus.events == []

