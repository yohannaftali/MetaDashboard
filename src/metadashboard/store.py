"""SQLite store for MetaDashboard: the MT5 terminal path and the accounts (login, server, investor password).

Investor passwords are encrypted with Windows DPAPI (only the same Windows user on the same machine can read
them) and are never shown again.
"""
import base64
import datetime as dt
import sqlite3
import sys

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    login    INTEGER NOT NULL,
    server   TEXT NOT NULL,
    password TEXT NOT NULL,
    enabled  INTEGER NOT NULL DEFAULT 1,
    start_date TEXT NOT NULL DEFAULT '',  -- YYYY-MM-DD: history before it is left out ('' = all)
    UNIQUE (login, server)
);
"""


# --------------------------------------------------------------------------------------------- DPAPI
def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    crypt = ctypes.windll.crypt32
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(dst)):  # 0x1 = UI_FORBIDDEN
        raise OSError('DPAPI %s failed' % ('encrypt' if protect else 'decrypt'))
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def encrypt(password):
    if sys.platform == 'win32':
        return 'dpapi:' + base64.b64encode(_dpapi(password.encode('utf-8'), True)).decode()
    return 'plain:' + password


def decrypt(value):
    kind, _, rest = value.partition(':')
    if kind == 'dpapi':
        return _dpapi(base64.b64decode(rest), False).decode('utf-8')
    return rest


# --------------------------------------------------------------------------------------------- store
class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)  # Flet runs handlers in threads
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        columns = {r['name'] for r in self.db.execute('PRAGMA table_info(accounts)')}
        if 'start_date' not in columns:  # a database made before start dates existed
            with self.db:
                self.db.execute("ALTER TABLE accounts ADD COLUMN start_date TEXT NOT NULL DEFAULT ''")

    def get(self, key, default=''):
        row = self.db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return row['value'] if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute('INSERT INTO settings (key, value) VALUES (?, ?) '
                            'ON CONFLICT (key) DO UPDATE SET value = excluded.value', (key, value))

    def accounts(self, with_password=False, enabled_only=False):
        sql = 'SELECT * FROM accounts' + (' WHERE enabled = 1' if enabled_only else '') + ' ORDER BY id'
        out = []
        for r in self.db.execute(sql):
            a = dict(id=r['id'], name=r['name'], login=r['login'], server=r['server'], enabled=bool(r['enabled']),
                     has_password=bool(r['password']), start_date=r['start_date'])
            if with_password:
                a['password'] = decrypt(r['password'])
            out.append(a)
        return out

    def save_account(self, name, login, server, password=None, enabled=True, id=None, start_date=''):
        """Insert (id None) or update. On update an empty password keeps the stored one. Without a password the
        terminal's saved one is used (logged in there once with "Save password"). start_date: YYYY-MM-DD from which
        the account counts (e.g. an old account that traded another strategy before), '' = its whole history."""
        name, server, start_date = (name or '').strip(), (server or '').strip(), (start_date or '').strip()
        login = int(login)
        if not name or not server or login <= 0:
            raise ValueError('name, login and server are required')
        if start_date:
            try:
                start_date = dt.date.fromisoformat(start_date).isoformat()
            except ValueError:
                raise ValueError('start date: use YYYY-MM-DD, e.g. 2026-09-01') from None
        with self.db:
            if id is None:
                cur = self.db.execute('INSERT INTO accounts (name, login, server, password, enabled, start_date) '
                                      'VALUES (?, ?, ?, ?, ?, ?)',
                                      (name, login, server, encrypt(password) if password else '', int(enabled),
                                       start_date))
                return cur.lastrowid
            cur = self.db.execute('UPDATE accounts SET name = ?, login = ?, server = ?, enabled = ?, start_date = ? '
                                  'WHERE id = ?', (name, login, server, int(enabled), start_date, id))
            if not cur.rowcount:
                raise ValueError('account %s not found' % id)
            if password:
                self.db.execute('UPDATE accounts SET password = ? WHERE id = ?', (encrypt(password), id))
            return id

    def delete_account(self, id):
        with self.db:
            self.db.execute('DELETE FROM accounts WHERE id = ?', (id,))

    def import_env(self, env, accounts):
        """One-time import of a .env (terminal path + accounts) into an empty store."""
        if env.get('MT5_TERMINAL_PATH') and not self.get('terminal_path'):
            self.set('terminal_path', env['MT5_TERMINAL_PATH'])
        n = 0
        for a in accounts:
            try:
                self.save_account(a['name'], a['login'], a['server'], a['password'])
                n += 1
            except sqlite3.IntegrityError:
                pass  # same login + server already there
        return n
