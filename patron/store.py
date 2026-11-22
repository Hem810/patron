"""SQLite state: jobs, checkpoints, response cache, cost ledger, approvals and actions."""
import json
import sqlite3
from contextlib import contextmanager

from . import config
from .text import now

SCHEMA = """
create table if not exists jobs(
  id text primary key, request_key text, request text, status text, message text,
  created text, updated text);
create index if not exists jobs_key on jobs(request_key);
create table if not exists steps(job text, name text, output text, at text, primary key(job, name));
create table if not exists responses(job text, key text, body text, at text, primary key(job, key));
create table if not exists ledger(
  id integer primary key, job text, key text, service text, op text, outcome text,
  credits real default 0, tokens integer default 0, ms integer default 0, detail text, at text);
create table if not exists approvals(
  id integer primary key, job text, packet_sha text, decision text, approver text, at text);
create table if not exists actions(key text primary key, job text, kind text, target text, at text);
"""


@contextmanager
def db():
    con = sqlite3.connect(config.data_dir() / "patron.db", timeout=20)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def init():
    with db() as c:
        c.execute("pragma journal_mode=wal")
        c.executescript(SCHEMA)


def one(sql, *args):
    with db() as c:
        row = c.execute(sql, args).fetchone()
    return dict(row) if row else None


def every(sql, *args):
    with db() as c:
        return [dict(row) for row in c.execute(sql, args).fetchall()]


def run(sql, *args):
    with db() as c:
        return c.execute(sql, args).lastrowid


def set_status(job, status, message=""):
    run("update jobs set status=?, message=?, updated=? where id=?", status, message, now(), job)


def get_step(job, name):
    row = one("select output from steps where job=? and name=?", job, name)
    return json.loads(row["output"]) if row else None


def put_step(job, name, output):
    run("insert or replace into steps values(?,?,?,?)", job, name, json.dumps(output, ensure_ascii=False), now())
