#!/usr/bin/env python3
"""Binary plist viewer. Requires only Python's standard library and Tk."""
import argparse
import base64
import datetime
import json
import math
from pathlib import Path
import plistlib
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import xml.etree.ElementTree as ET


def load_document(path):
    """Detect by content, returning (value, human-readable format)."""
    contents = Path(path).read_bytes()
    if contents.startswith(b'bplist'):
        if contents[:8] != b'bplist00':
            raise ValueError(f'Unsupported binary plist version: {contents[:8]!r}')
        return plistlib.loads(contents, fmt=plistlib.FMT_BINARY), 'Binary plist'
    try:
        root = ET.fromstring(contents)
    except ET.ParseError as error:
        raise ValueError('File is neither a binary plist nor a valid XML plist.') from error
    if root.tag != 'plist':
        raise ValueError('XML document must have a <plist> root element.')
    return plistlib.loads(contents, fmt=plistlib.FMT_XML), 'XML plist'


def load_plist(path):
    return load_document(path)[0]


def type_name(value):
    if isinstance(value, plistlib.UID):
        return 'UID'
    return {dict: 'Dictionary', list: 'Array', bytes: 'Data',
            str: 'String', bool: 'Boolean', int: 'Integer',
            float: 'Real', datetime.datetime: 'Date', type(None): 'Null'}.get(type(value), type(value).__name__)


def value_text(value):
    if isinstance(value, (dict, list)):
        return f'{len(value)} items'
    if isinstance(value, bytes):
        return f'Base64: {base64.b64encode(value).decode()}\nHex: {value.hex(" ")}'
    if isinstance(value, datetime.datetime):
        return value.isoformat() + ('Z' if value.tzinfo is None else '')
    if isinstance(value, plistlib.UID):
        return str(value.data)
    if isinstance(value, str):
        return value
    return repr(value)


def json_value(value, ancestors=None):
    """Convert non-JSON plist types to explicit tagged values; reject cycles."""
    ancestors = set() if ancestors is None else ancestors
    if isinstance(value, (dict, list)):
        if id(value) in ancestors:
            raise ValueError('Cannot export a cyclic property list as JSON.')
        ancestors = ancestors | {id(value)}
        if isinstance(value, dict):
            return {str(k): json_value(v, ancestors) for k, v in value.items()}
        return [json_value(v, ancestors) for v in value]
    if isinstance(value, bytes):
        return {'$type': 'data', 'base64': base64.b64encode(value).decode('ascii')}
    if isinstance(value, datetime.datetime):
        return {'$type': 'date', 'value': value_text(value)}
    if isinstance(value, plistlib.UID):
        return {'$type': 'uid', 'value': value.data}
    if isinstance(value, float) and not math.isfinite(value):
        return {'$type': 'real', 'value': repr(value)}
    return value


def walk_nodes(value):
    """Iterative preorder traversal including containers and cycle references."""
    stack = [('', 'root', '$', value, frozenset())]
    count = 0
    while stack:
        parent, key, path, item, ancestors = stack.pop()
        node = str(count)
        count += 1
        cycle = isinstance(item, (dict, list)) and id(item) in ancestors
        yield node, parent, key, path, item, cycle
        if isinstance(item, (dict, list)) and not cycle:
            ancestors = ancestors | {id(item)}
            children = list(item.items()) if isinstance(item, dict) else list(enumerate(item))
            for k, child in reversed(children):
                suffix = f'[{json.dumps(str(k), ensure_ascii=False)}]' if isinstance(item, dict) else f'[{k}]'
                stack.append((node, str(k), path + suffix, child, ancestors))


def text_export(value):
    lines = []
    for _, _, _, path, item, cycle in walk_nodes(value):
        display = '<cycle reference>' if cycle else value_text(item)
        # JSON quoting keeps multiline strings readable and unambiguous.
        lines.append(f'{path} ({type_name(item)}): {json.dumps(display, ensure_ascii=False)}')
    return '\n'.join(lines) + '\n'


class Viewer(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=10)
        self.pack(fill='both', expand=True)
        self.data = None
        self.loaded = False
        self.nodes = {}
        self.matches = []
        self.match_index = -1
        self.filename = None
        master.title('Binary Plist Viewer')
        master.geometry('1050x720')
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x', pady=(0, 8))
        for label, action in [('Open…', self.open_file), ('Export JSON…', lambda: self.export('json')),
                              ('Export text…', lambda: self.export('txt')),
                              ('Expand all', lambda: self.expand(True)), ('Collapse all', lambda: self.expand(False))]:
            ttk.Button(toolbar, text=label, command=action).pack(side='left', padx=(0, 6))
        search = ttk.Frame(self)
        search.pack(fill='x', pady=(0, 8))
        ttk.Label(search, text='Regex:').pack(side='left')
        self.pattern = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.pattern)
        entry.pack(side='left', fill='x', expand=True, padx=6)
        entry.bind('<Return>', lambda event: self.search())
        self.ignore_case = tk.BooleanVar(value=True)
        ttk.Checkbutton(search, text='Ignore case', variable=self.ignore_case).pack(side='left')
        ttk.Button(search, text='Search', command=self.search).pack(side='left', padx=6)
        ttk.Button(search, text='Previous', command=lambda: self.step(-1)).pack(side='left')
        ttk.Button(search, text='Next', command=lambda: self.step(1)).pack(side='left', padx=6)
        self.result_status = tk.StringVar(value='No search')
        ttk.Label(search, textvariable=self.result_status, width=20).pack(side='left')
        self.pattern.trace_add('write', self.clear_search)
        self.ignore_case.trace_add('write', self.clear_search)
        panes = ttk.Panedwindow(self, orient='vertical')
        panes.pack(fill='both', expand=True)
        tree_frame = ttk.Frame(panes)
        self.tree = ttk.Treeview(tree_frame, columns=('type', 'value'), selectmode='browse')
        self.tree.heading('#0', text='Key / Index')
        self.tree.heading('type', text='Type')
        self.tree.heading('value', text='Value')
        self.tree.column('#0', width=300)
        self.tree.column('type', width=110, stretch=False)
        self.tree.column('value', width=570)
        self.tree.grid(row=0, column=0, sticky='nsew')
        ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview).grid(row=0, column=1, sticky='ns')
        ttk.Scrollbar(tree_frame, orient='horizontal', command=self.tree.xview).grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=tree_frame.grid_slaves(row=0, column=1)[0].set,
                            xscrollcommand=tree_frame.grid_slaves(row=1, column=0)[0].set)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        panes.add(tree_frame, weight=3)
        detail_frame = ttk.LabelFrame(panes, text='Selected node — full value')
        self.detail = tk.Text(detail_frame, wrap='word', height=10, state='disabled')
        self.detail.pack(side='left', fill='both', expand=True)
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.detail.yview)
        detail_scroll.pack(side='right', fill='y')
        self.detail.configure(yscrollcommand=detail_scroll.set)
        panes.add(detail_frame, weight=1)
        self.status = tk.StringVar(value='Open a binary or XML property list to begin.')
        ttk.Label(self, textvariable=self.status).pack(fill='x', pady=(8, 0))
        self.tree.bind('<<TreeviewSelect>>', self.show_detail)
        master.bind('<Control-o>', lambda event: self.open_file())
        master.bind('<Command-o>', lambda event: self.open_file())
        master.bind('<F3>', lambda event: self.step(1))
        master.bind('<Shift-F3>', lambda event: self.step(-1))

    def clear_search(self, *_):
        self.matches = []
        self.match_index = -1
        self.result_status.set('No search')

    def open_file(self, path=None):
        path = path or filedialog.askopenfilename(filetypes=[('Property lists', '*.plist *.bplist'), ('All files', '*')])
        if not path:
            return
        try:
            data, file_format = load_document(path)
            nodes = list(walk_nodes(data))
        except Exception as error:
            messagebox.showerror('Unable to open plist', str(error))
            return
        self.tree.delete(*self.tree.get_children())
        self.nodes.clear()
        self.data, self.loaded, self.filename = data, True, Path(path)
        self.clear_search()
        for node, parent, key, node_path, value, cycle in nodes:
            full = '<cycle reference>' if cycle else value_text(value)
            preview = full.replace('\n', ' ↵ ').replace('\r', '')
            if len(preview) > 160:
                preview = preview[:157] + '…'
            self.tree.insert(parent, 'end', iid=node, text=key,
                             values=(type_name(value), preview), open=not parent)
            self.nodes[node] = (node_path, key, value, full)
        self.tree.selection_set('0')
        self.tree.focus('0')
        self.show_detail()
        self.master.title(f'{self.filename.name} — Binary Plist Viewer')
        self.status.set(f'{self.filename}  •  {file_format}  •  {len(nodes)} nodes')

    def show_detail(self, *_):
        selection = self.tree.selection()
        if not selection:
            return
        path, _, value, full = self.nodes[selection[0]]
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', f'{path}\nType: {type_name(value)}\n\n{full}')
        self.detail.configure(state='disabled')

    def expand(self, opened):
        for node in self.nodes:
            self.tree.item(node, open=opened)

    def search(self):
        self.clear_search()
        if not self.loaded or not self.pattern.get():
            return
        try:
            regex = re.compile(self.pattern.get(), re.IGNORECASE if self.ignore_case.get() else 0)
        except re.error as error:
            messagebox.showerror('Invalid regular expression', str(error))
            return
        self.matches = [node for node, (path, key, value, full) in self.nodes.items()
                        if any(regex.search(field) for field in (path, key, type_name(value), full))]
        if self.matches:
            self.step(1)
        else:
            self.result_status.set('No matches')

    def step(self, direction):
        if not self.matches:
            return
        self.match_index = (self.match_index + direction) % len(self.matches)
        node = self.matches[self.match_index]
        parent = self.tree.parent(node)
        while parent:
            self.tree.item(parent, open=True)
            parent = self.tree.parent(parent)
        self.tree.selection_set(node)
        self.tree.focus(node)
        self.tree.see(node)
        self.show_detail()
        self.result_status.set(f'{self.match_index + 1} of {len(self.matches)} nodes')

    def export(self, kind):
        if not self.loaded:
            messagebox.showinfo('Export', 'Open a property list first.')
            return
        try:
            output = (json.dumps(json_value(self.data), indent=2, ensure_ascii=False, allow_nan=False) + '\n'
                      if kind == 'json' else text_export(self.data))
        except Exception as error:
            messagebox.showerror('Unable to export', str(error))
            return
        path = filedialog.asksaveasfilename(defaultextension='.' + kind,
                    initialfile=self.filename.stem + '.' + kind,
                    filetypes=[('JSON' if kind == 'json' else 'Text', '*.' + kind)])
        if not path:
            return
        if Path(path).resolve() == self.filename.resolve():
            messagebox.showerror('Unable to export', 'Choose a different path from the source plist.')
            return
        try:
            Path(path).write_text(output, encoding='utf-8')
        except OSError as error:
            messagebox.showerror('Unable to export', str(error))
            return
        self.status.set(f'Exported {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', nargs='?', help='Optional plist to open on startup')
    args = parser.parse_args()
    try:
        root = tk.Tk()
    except tk.TclError as error:
        parser.exit(1, f'Unable to start Tk UI: {error}\n')
    viewer = Viewer(root)
    if args.file:
        root.after(0, lambda: viewer.open_file(args.file))
    root.mainloop()


if __name__ == '__main__':
    main()
