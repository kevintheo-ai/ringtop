"""The programs for the nodes as the texts they travel as: several files joined into one program, checked as a whole."""

import ast
import builtins
import collections
import symtable

from ringtop_parts.connect import shell
from ringtop_parts.connect.shell import BACKFILL, DISCOVER, SAMPLER

PROGRAMS = {"sampler": shell.SAMPLER_PARTS, "discover": ["discover.py"], "backfill": ["backfill.py"]}


def loose_ends(text):
    """What a linter finds in one file and cannot find across several: names that are read but bound nowhere, modules
    imported and never used, functions and classes that stand twice. Three sorted lists."""
    top = symtable.symtable(text, "program", "exec")
    bound = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    tables, unknown, used = [top], set(), set()
    for table in tables:  # grows while it runs: every scope below the top one
        tables.extend(table.get_children())
        for symbol in table.get_symbols():
            if symbol.is_referenced() and (table is top or symbol.is_global()):
                used.add(symbol.get_name())
                if symbol.get_name() not in bound and not hasattr(builtins, symbol.get_name()):
                    unknown.add(symbol.get_name())
    unused = {s.get_name() for s in top.get_symbols() if s.is_imported()} - used
    names = collections.Counter(n.name for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)))
    return sorted(unknown), sorted(unused), sorted(name for name, count in names.items() if count > 1)


def test_a_node_gets_the_files_joined_and_an_old_python_can_read_them():
    """Nothing is installed on a node: each program goes to its `python3 -` as one text, whatever Python that is. So
    the joined text has to compile, and with nothing newer than the grammar of Python 3.8."""
    assert shell.program(shell.SAMPLER_PARTS) == SAMPLER and shell.SAMPLER_PARTS[-1] == "sampler/loop.py"
    assert shell.program(["discover.py"]) == DISCOVER and shell.program(["backfill.py"]) == BACKFILL
    for name, parts in PROGRAMS.items():
        text = shell.program(parts)
        compile(text, name, "exec")
        ast.parse(text, feature_version=(3, 8))
        for part in parts:
            # The edit hook rewrites Python for the newest version, and a rule family cannot be switched off by name:
            # this line keeps every linter off the file. What a linter would have found, the check below finds.
            assert (shell.NODE / part).read_text(encoding="utf-8").startswith("# ruff: noqa\n"), part


def test_every_name_a_program_reads_is_bound_somewhere_in_it():
    """The parts of the sampler share one namespace once they are joined, so a linter that reads file by file cannot
    tell a name from another part from a typing mistake. The joined text can: every name read is bound at the top
    level or built in, every import is used, and no function or class stands twice (the later one would win)."""
    broken = "import os, json\n\n\ndef f():\n    return missing(json)\n\n\ndef f():\n    return 1\n"
    assert loose_ends(broken) == (["missing"], ["os"], ["f"])  # the check sees what it is there for
    for name, parts in PROGRAMS.items():
        assert loose_ends(shell.program(parts)) == ([], [], []), name


def test_every_piece_of_a_program_for_the_nodes_says_what_it_is_for():
    """The files for the nodes keep linters off (see above), so the rule of one sentence per file, function and class
    is checked here: every file opens with a sentence, every function and class of its top level carries one. And
    the text stays plain ASCII: a node reads it with whatever locale it has."""
    for name, parts in PROGRAMS.items():
        for part in parts:
            tree = ast.parse((shell.NODE / part).read_text(encoding="utf-8"))
            assert ast.get_docstring(tree), part
            silent = [
                n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not ast.get_docstring(n)
            ]
            assert not silent, (part, silent)
        assert shell.program(parts).isascii(), name
