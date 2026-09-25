"""Operator-only native Oracle archive / shadow restore / reset / recovery.

No startup hook, web endpoint, external file export, model call or credential log.
No write occurs without --commit and --services-stopped. Archive and rehearsal
tables remain in the same restricted schema; obtain a separate DBA backup for
database-loss recovery. Never use this tool to reset shared schemas.
"""
import argparse
import hashlib
import json
import re
import sys
from contextlib import contextmanager, nullcontext

from app.accounts import execute
from app.errors import ServiceError
from app.execution_store import execute as clob_execute
from app.onboarding_schema import verify as verify_schema
from app.roster_audit import (
    ARCHIVE_TABLES,
    BACKUP_PREFIXES,
    PROTECTED_TABLES,
    RETAINED_UTILITY_TABLES,
    archive_order,
    digest,
)
from app.storage import document, rows


def demand(ok, message):
    if not ok:
        raise ServiceError('ROSTER_RESET_STOPPED', message, 409)


def identifier(value):
    demand(isinstance(value, str) and re.fullmatch(r'[A-Z][A-Z0-9_$]{0,127}', value), 'Unexpected schema identifier.')
    return value


@contextmanager
def maintenance_lock(c):
    """Session-scoped lock survives Oracle DDL commits; fail closed if unavailable."""
    import oracledb
    with c.cursor() as cursor:
        result = cursor.var(int)
        try:
            cursor.execute('BEGIN :result := DBMS_LOCK.REQUEST(id=>173592008,lockmode=>6,timeout=>0,release_on_commit=>FALSE); END;', result=result)
        except oracledb.DatabaseError as error:
            raise ServiceError('MAINTENANCE_LOCK_UNAVAILABLE', 'A DBA must approve DBMS_LOCK access for this recovery tool. No archive/reset was started.', 503) from error
        demand(result.getvalue() == 0, 'Another maintenance operation holds the recovery lock.')
    try:
        yield
    except BaseException:
        c.rollback()  # release row/table locks before handing maintenance to another operator
        raise
    finally:
        with c.cursor() as cursor:
            result = cursor.var(int)
            cursor.execute('BEGIN :result := DBMS_LOCK.RELEASE(173592008); END;', result=result)
            demand(result.getvalue() == 0, 'Maintenance lock release failed; keep writers stopped.')


def native_name(batch, kind, index):
    demand(re.fullmatch(r'roster4-[a-zA-Z0-9_-]{1,22}', batch), 'Use a roster4- batch ID, maximum 30 characters.')
    demand(kind in ('B', 'T') and 0 <= index < 100, 'Invalid archive object.')
    return f'R4{kind}_{hashlib.sha256(batch.encode()).hexdigest()[:12].upper()}_{index:02d}'


def stopped(c):
    who = rows(c, "SELECT USER owner_name,SYS_CONTEXT('USERENV','CURRENT_SCHEMA') schema_name FROM dual")
    demand(who == [{'owner_name': 'AI_POD_STAFFING', 'schema_name': 'AI_POD_STAFFING'}], 'Use AI_POD_STAFFING only.')
    demand(rows(c, "SELECT runtime_id FROM staffing_runtime WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N'"), 'Disable agent/notification switches; keep all app writers stopped.')
    demand(not rows(c, "SELECT execution_id FROM agent_executions WHERE status IN ('QUEUED','RUNNING')"), 'Queued/running work must be resolved before maintenance.')


def columns(c, table):
    return rows(c, """SELECT column_name,data_type,data_length,data_precision,data_scale,nullable,column_id
        FROM user_tab_columns WHERE table_name=:tableName ORDER BY column_id""", tableName=table)


def json_columns(c, table, meta):
    """Return JSON columns from driver metadata without reading employee values."""
    names = [identifier(column['column_name']) for column in meta]
    demand(names, 'Missing table metadata.')
    with c.cursor() as cursor:
        cursor.execute(f"SELECT {','.join(names)} FROM {identifier(table)} WHERE 1=0")
        return [name for name, info in zip(names, cursor.description, strict=True) if info.is_json]


def fingerprint(c, table, meta, json_names=()):
    """SQL renders numbers and nanosecond timestamps losslessly; never exports raw row values."""
    identifier(table)
    projection = []
    json_names = set(json_names)
    for column in meta:
        name, kind = identifier(column['column_name']), column['data_type']
        if name in json_names:
            # python-oracledb automatically decodes IS JSON columns to dict/list,
            # while CTAS archive columns (without the constraint) return text.
            # Force both sides to their original textual representation so the
            # same stored value always has the same content fingerprint.
            demand(kind in ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR', 'CLOB', 'NCLOB'),
                   'JSON archive storage needs a reviewed textual adapter.')
            projection.append(f'TO_CLOB({name}) {name}')
        elif kind == 'NUMBER':
            projection.append(f"TO_CHAR({name},'TM9','NLS_NUMERIC_CHARACTERS=''.,''') {name}")
        elif kind == 'DATE':
            projection.append(f"TO_CHAR({name},'YYYY-MM-DD\"T\"HH24:MI:SS') {name}")
        elif kind.startswith('TIMESTAMP'):
            demand('LOCAL TIME ZONE' not in kind, 'Local-zone timestamp needs a reviewed adapter.')
            fmt = 'YYYY-MM-DD"T"HH24:MI:SS.FF9'+('TZH:TZM' if 'WITH TIME ZONE' in kind else '')
            projection.append(f"TO_CHAR({name},'{fmt}') {name}")
        else:
            demand(kind in ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR', 'CLOB', 'NCLOB', 'BLOB', 'RAW', 'JSON'), 'Unsupported archive data type.')
            projection.append(name)
    demand(projection, 'Missing table metadata.')
    hashes = []
    with c.cursor() as cursor:
        cursor.execute(f"SELECT {','.join(projection)} FROM {table}")
        while batch := cursor.fetchmany(500):
            hashes.extend(digest(row) for row in batch)
            demand(len(hashes) <= 250000, 'Archive exceeds reviewed per-table row limit; use DBA recovery tooling.')
    return {'count': len(hashes), 'sha256': digest(sorted(hashes))}


def constraints(c):
    found = rows(c, """SELECT a.constraint_name,a.table_name,a.constraint_type,a.status,a.validated,
        a.search_condition_vc check_text,b.table_name parent_table,a.r_owner,
        (SELECT LISTAGG(x.column_name,',') WITHIN GROUP(ORDER BY x.position) FROM user_cons_columns x WHERE x.constraint_name=a.constraint_name) columns_list,
        (SELECT LISTAGG(x.column_name,',') WITHIN GROUP(ORDER BY x.position) FROM user_cons_columns x WHERE x.constraint_name=b.constraint_name) parent_columns
        FROM user_constraints a LEFT JOIN user_constraints b ON a.r_constraint_name=b.constraint_name
        ORDER BY a.constraint_name""")
    return [r for r in found if r['table_name'] in (*ARCHIVE_TABLES, *PROTECTED_TABLES)]


def trigger_metadata(c):
    found = rows(c, 'SELECT trigger_name,table_name,status FROM user_triggers ORDER BY trigger_name')
    result = {}
    for t in found:
        if t['table_name'] not in ARCHIVE_TABLES:
            continue
        name = identifier(t['trigger_name'])
        source = ''.join(r['text'] for r in rows(c, "SELECT text FROM user_source WHERE name=:name AND type='TRIGGER' ORDER BY line", name=name))
        result[name] = {**t, 'source': source, 'sha256': digest(source)}
    return result


def inventory(c):
    verify_schema(c)
    present = {r['table_name'] for r in rows(c, 'SELECT table_name FROM user_tables')}
    required = set(ARCHIVE_TABLES) | set(PROTECTED_TABLES)
    demand(required <= present, 'Required archive/protected tables missing.')
    unknown = present-required-{t for t in present if t.startswith((*BACKUP_PREFIXES, 'R4B_', 'R4T_'))}-RETAINED_UTILITY_TABLES
    demand(not unknown, 'Unclassified tables exist. Run roster_audit and review the scope.')
    keys = constraints(c)
    demand(all(k['status'] == 'ENABLED' and k['validated'] == 'VALIDATED' for k in keys), 'Constraints must be enabled and validated.')
    # Include consumers outside the reset allowlist, not just the constraints copied below.
    incoming = rows(c, """SELECT a.table_name child_table,b.table_name parent_table FROM user_constraints a
        JOIN user_constraints b ON a.r_constraint_name=b.constraint_name AND a.r_owner=USER WHERE a.constraint_type='R'""")
    demand(not any(k['parent_table'] in ARCHIVE_TABLES and k['child_table'] not in ARCHIVE_TABLES for k in incoming), 'An outside table references reset data; review scope before proceeding.')
    order, cycles = archive_order(ARCHIVE_TABLES, incoming)
    demand(not cycles, 'Circular dependencies require a reviewed migration.')
    demand(not rows(c, """SELECT table_name FROM user_tab_identity_cols WHERE generation_type='ALWAYS'
        AND table_name IN (""" + ','.join("'"+t+"'" for t in ARCHIVE_TABLES) + ')'), 'Always-generated identities require a reviewed restore adapter.')
    demand(not rows(c, """SELECT table_name FROM user_tab_cols WHERE (virtual_column='YES' OR hidden_column='YES')
        AND user_generated='YES' AND table_name IN (""" + ','.join("'"+t+"'" for t in ARCHIVE_TABLES) + ')'), 'Generated or hidden user columns require a reviewed adapter.')
    meta = {t: columns(c, t) for t in sorted(required)}
    json_meta = {t: json_columns(c, t, meta[t]) for t in sorted(required)}
    guards = trigger_metadata(c)
    demand(all(t['status'] == 'ENABLED' and t['source'] for t in guards.values()), 'Restore disabled guards before preparing an archive.')
    return {'columns': meta, 'json_columns': json_meta, 'keys': keys, 'order': order, 'triggers': guards,
            'fingerprints': {t: fingerprint(c, t, meta[t], json_meta[t]) for t in sorted(required)}}


def lock_tables(c, extra=()):
    for t in sorted({*ARCHIVE_TABLES, *PROTECTED_TABLES, *extra}):
        execute(c, f'LOCK TABLE {identifier(t)} IN EXCLUSIVE MODE NOWAIT')


def run(c, batch):
    result = rows(c, 'SELECT status,metadata_json FROM roster_reset_runs WHERE batch_id=:batch', batch=batch)
    demand(len(result) == 1, 'Unknown archive batch.')
    meta = document(result[0]['metadata_json'])
    demand(meta['batch'] == batch and set(meta['archives']) == set(ARCHIVE_TABLES), 'Archive scope does not match this release.')
    for i, t in enumerate(sorted(ARCHIVE_TABLES)):
        demand(meta['archives'][t] == native_name(batch, 'B', i) and meta['shadows'][t] == native_name(batch, 'T', i), 'Unexpected archive table names.')
    return result[0]['status'], meta


def save(c, meta, state):
    clob_execute(c, 'UPDATE roster_reset_runs SET status=:state,metadata_json=:payload WHERE batch_id=:batch',
                 {'state': state, 'payload': json.dumps(meta), 'batch': meta['batch']}, ('payload',))


def upgrade_preparing_fingerprints(c, meta):
    """Upgrade the one pre-fix PREPARING journal only after proving live data is unchanged."""
    if 'json_columns' in meta:
        return meta
    # The old fingerprint is still authoritative for this check because it is
    # exactly how the PREPARING snapshot was produced. Do not update ARCHIVED,
    # REHEARSED or reset batches under a new fingerprint representation.
    verify_live(c, meta)
    for t, archive_name in meta['archives'].items():
        demand(fingerprint(c, archive_name, meta['columns'][t])['count'] == 0,
               'Legacy archive contains rows; inspect it before upgrading the journal.')
    meta['json_columns'] = {t: json_columns(c, t, meta['columns'][t]) for t in meta['columns']}
    meta['fingerprints'] = {
        t: fingerprint(c, t, meta['columns'][t], meta['json_columns'][t]) for t in meta['columns']
    }
    meta['confirmation'] = digest({'batch': meta['batch'], 'fingerprints': meta['fingerprints'],
                                   'columns': meta['columns'], 'keys': meta['keys']})
    save(c, meta, 'PREPARING')
    c.commit()  # durable representation upgrade before any archive copy DDL/DML
    return meta


def verify_archive(c, meta):
    for t, archive in meta['archives'].items():
        demand(fingerprint(c, archive, meta['columns'][t], meta.get('json_columns', {}).get(t, ())) == meta['fingerprints'][t], 'Archive data is incomplete or changed; no reset allowed.')


def verify_live(c, meta, *, empty=False, guards_disabled=False):
    stopped(c)
    demand(constraints(c) == meta['keys'], 'Constraints changed since the archive.')
    guards = trigger_metadata(c)
    demand(set(guards) == set(meta['triggers']), 'Trigger inventory changed.')
    for name, old in meta['triggers'].items():
        demand(guards[name]['sha256'] == old['sha256'] and guards[name]['status'] == ('DISABLED' if guards_disabled else old['status']), 'Trigger state or definition changed.')
    for t, cols in meta['columns'].items():
        demand(columns(c, t) == cols, 'Table columns changed since the archive.')
        actual = fingerprint(c, t, cols, meta.get('json_columns', {}).get(t, ()))
        expected = {'count': 0, 'sha256': digest([])} if empty and t in ARCHIVE_TABLES else meta['fingerprints'][t]
        demand(actual == expected, 'Live data differs from the approved archive. Do not reset or restore over new writes.')


def prepare(c, batch, operator):
    stopped(c)
    demand(not rows(c, 'SELECT batch_id FROM roster_reset_runs WHERE batch_id=:batch', batch=batch), 'Batch already exists. Inspect it or resume-archive; never overwrite.')
    meta = inventory(c)
    meta.update(batch=batch, operator=operator,
        archives={t: native_name(batch, 'B', i) for i, t in enumerate(sorted(ARCHIVE_TABLES))},
        shadows={t: native_name(batch, 'T', i) for i, t in enumerate(sorted(ARCHIVE_TABLES))})
    meta['ddl'] = {}
    for t in ARCHIVE_TABLES:
        ddl = rows(c, "SELECT DBMS_METADATA.GET_DDL('TABLE',:name,USER) ddl FROM dual", name=t)[0]['ddl']
        meta['ddl'][t] = ddl.read() if hasattr(ddl, 'read') else ddl
    meta['confirmation'] = digest({'batch': batch, 'fingerprints': meta['fingerprints'], 'columns': meta['columns'], 'keys': meta['keys']})
    clob_execute(c, "INSERT INTO roster_reset_runs(batch_id,status,metadata_json,operator_name) VALUES(:batch,'PREPARING',:payload,:operator)",
                 {'batch': batch, 'payload': json.dumps(meta), 'operator': operator}, ('payload',))
    c.commit()  # durable intent before Oracle DDL; original business tables unchanged
    return archive(c, batch)


def create_empty(c, name, original, meta):
    exists = rows(c, 'SELECT object_type FROM user_objects WHERE object_name=:name', name=name)
    if not exists:
        cols = ','.join(identifier(col['column_name']) for col in meta['columns'][original])
        execute(c, f'CREATE TABLE {identifier(name)} AS SELECT {cols} FROM {identifier(original)} WHERE 1=0')
        execute(c, f"COMMENT ON TABLE {name} IS 'ROSTER_RESET:{meta['batch']}:{original}'")
    else:
        demand(len(exists) == 1 and exists[0]['object_type'] == 'TABLE', 'Unexpected archive/shadow object.')
    marker = rows(c, 'SELECT comments FROM user_tab_comments WHERE table_name=:name', name=name)
    demand(marker == [{'comments': f"ROSTER_RESET:{meta['batch']}:{original}"}], 'Archive/shadow ownership marker missing. Inspect interrupted DDL before resuming.')
    # CTAS deliberately does not copy identity/default expressions. Types and precision must match.
    def shape(cols):
        return [{k: v for k, v in col.items() if k != 'nullable'} for col in cols]
    demand(shape(columns(c, name)) == shape(meta['columns'][original]), 'Archive/shadow column definitions differ.')


def archive(c, batch):
    state, meta = run(c, batch)
    demand(state == 'PREPARING', 'Only an interrupted PREPARING batch can resume archiving.')
    meta = upgrade_preparing_fingerprints(c, meta)
    verify_live(c, meta)
    for t, name in meta['archives'].items():
        create_empty(c, name, t, meta)
    lock_tables(c, meta['archives'].values())
    verify_live(c, meta)
    for t, name in meta['archives'].items():
        demand(fingerprint(c, name, meta['columns'][t], meta['json_columns'].get(t, ()))['count'] == 0, 'Prepared archive unexpectedly contains rows. Inspect before retrying.')
        cols = ','.join(identifier(col['column_name']) for col in meta['columns'][t])
        execute(c, f'INSERT INTO {name}({cols}) SELECT {cols} FROM {t}')
    verify_archive(c, meta)
    save(c, meta, 'ARCHIVED')
    return {'batch': batch, 'status': 'ARCHIVED', 'counts': {t: meta['fingerprints'][t]['count'] for t in ARCHIVE_TABLES}, 'business_data_changed': False}


def rehearse(c, batch):
    state, meta = run(c, batch)
    demand(state in ('ARCHIVED', 'REHEARSED'), 'Archive must be complete before rehearsal.')
    verify_live(c, meta)
    verify_archive(c, meta)
    for t, name in meta['shadows'].items():
        create_empty(c, name, t, meta)
    lock_tables(c, [*meta['archives'].values(), *meta['shadows'].values()])
    verify_live(c, meta)
    verify_archive(c, meta)
    for t in reversed(meta['order']):
        shadow, original = meta['shadows'][t], meta['archives'][t]
        existing = fingerprint(c, shadow, meta['columns'][t], meta['json_columns'].get(t, ()))
        demand(existing['count'] == 0 or existing == meta['fingerprints'][t], 'Shadow recovery data differs; do not overwrite it.')
        if not existing['count']:
            cols = ','.join(identifier(col['column_name']) for col in meta['columns'][t])
            execute(c, f'INSERT INTO {shadow}({cols}) SELECT {cols} FROM {original}')
        demand(fingerprint(c, shadow, meta['columns'][t], meta['json_columns'].get(t, ())) == meta['fingerprints'][t], 'Restore round-trip verification failed.')
    # Verify actual restored values against original check and relationship rules.
    for k in meta['keys']:
        if k['table_name'] not in ARCHIVE_TABLES:
            continue
        target = meta['shadows'][k['table_name']]
        cols = [identifier(col) for col in (k['columns_list'] or '').split(',') if col]
        if k['constraint_type'] == 'C':
            demand(k['check_text'] and len(k['check_text']) < 4000, 'Check expression requires reviewed restore tooling.')
            query = f"SELECT COUNT(*) n FROM {target} WHERE NOT ({k['check_text']})"
        elif k['constraint_type'] in ('P', 'U'):
            query = f"SELECT COUNT(*) n FROM (SELECT {','.join(cols)} FROM {target} WHERE " + ' OR '.join(f'{x} IS NOT NULL' for x in cols) + f" GROUP BY {','.join(cols)} HAVING COUNT(*)>1)"
        elif k['constraint_type'] == 'R':
            demand(k['r_owner'] == 'AI_POD_STAFFING', 'Cross-schema dependency requires separate recovery review.')
            parent = meta['shadows'].get(k['parent_table'], identifier(k['parent_table']))
            pcols = [identifier(col) for col in k['parent_columns'].split(',')]
            query = f"SELECT COUNT(*) n FROM {target} child WHERE " + ' AND '.join(f'child.{x} IS NOT NULL' for x in cols)
            query += f" AND NOT EXISTS (SELECT 1 FROM {parent} parent WHERE " + ' AND '.join(f'child.{a}=parent.{b}' for a, b in zip(cols, pcols, strict=True)) + ')'
        else:
            demand(False, 'Unexpected constraint type.')
        demand(rows(c, query)[0]['n'] == 0, 'Restored shadow data violates the original schema rules.')
    meta['rehearsal'] = {'mode': 'isolated_native_shadow_tables', 'constraints_checked': True, 'fingerprint': meta['confirmation']}
    save(c, meta, 'REHEARSED')
    return {'batch': batch, 'status': 'REHEARSED', 'reset_confirmation': meta['confirmation'], 'business_data_changed': False}


def restore_guards(c, meta):
    current = trigger_metadata(c)
    demand(set(current) == set(meta['triggers']), 'Guard inventory changed; manual recovery review required.')
    for name, old in meta['triggers'].items():
        demand(current[name]['sha256'] == old['sha256'], 'Guard definition changed; do not overwrite it.')
    failed = []
    for name in meta['triggers']:
        try:
            execute(c, f'ALTER TRIGGER {identifier(name)} ENABLE')
        except Exception:
            failed.append(name)
    demand(not failed, 'Guard restoration failed. Keep services stopped and use recover-guards.')


def mutate(c, batch, confirmation, restore=False):
    state, meta = run(c, batch)
    demand(state == ('RESET' if restore else 'REHEARSED'), 'Batch state does not permit this operation. Inspect before retrying.')
    demand(confirmation == meta['confirmation'] and meta.get('rehearsal', {}).get('fingerprint') == confirmation, 'Supply the exact verified rehearsal fingerprint.')
    verify_archive(c, meta)
    verify_live(c, meta, empty=restore)
    try:
        # Only these archived-table triggers; no constraints or protected-table triggers are disabled.
        # DDL commits individually; journal+unchanged original source permit explicit guard recovery.
        for name in meta['triggers']:
            execute(c, f'ALTER TRIGGER {identifier(name)} DISABLE')
        lock_tables(c, meta['archives'].values())
        verify_archive(c, meta)
        verify_live(c, meta, empty=restore, guards_disabled=True)
        if restore:
            for t in reversed(meta['order']):
                cols = ','.join(identifier(col['column_name']) for col in meta['columns'][t])
                execute(c, f"INSERT INTO {t}({cols}) SELECT {cols} FROM {meta['archives'][t]}")
            verify_live(c, meta, guards_disabled=True)
            # Verify exact recovery first, then deliberately revoke all restored sessions.
            execute(c, 'UPDATE app_sessions SET revoked_at=SYSTIMESTAMP WHERE revoked_at IS NULL')
        else:
            for t in meta['order']:
                execute(c, f'DELETE FROM {identifier(t)}')
            verify_live(c, meta, empty=True, guards_disabled=True)
        save(c, meta, 'RESTORED' if restore else 'RESET')
        c.commit()  # atomic business operation BEFORE guard-enable DDL
    except BaseException:
        c.rollback()
        raise
    finally:
        restore_guards(c, meta)
    return {'batch': batch, 'status': 'RESTORED' if restore else 'RESET', 'archive_retained': True,
            'protected_data_unchanged': True, 'sessions_revoked': restore, 'runtime_switches': 'OFF'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'inspect', 'archive', 'resume-archive', 'rehearse', 'reset', 'restore', 'recover-guards'])
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--batch', required=True)
    parser.add_argument('--operator', default='')
    parser.add_argument('--confirmation', default='')
    parser.add_argument('--services-stopped', action='store_true')
    parser.add_argument('--commit', action='store_true')
    args = parser.parse_args()
    native_name(args.batch, 'B', 0)
    readonly = args.action in ('plan', 'inspect')
    if not readonly and (not args.commit or not args.services_stopped or not args.operator.strip() or len(args.operator) > 255):
        parser.error('Writes require --commit, --services-stopped and a named --operator. No database operation attempted.')
    from app.config import Settings
    from app.database import OracleDatabase
    db = OracleDatabase(Settings(_env_file=args.env_file))
    try:
        with (db.read() if readonly else db.write()) as c, (nullcontext() if readonly else maintenance_lock(c)):
            if args.action == 'plan':
                meta = inventory(c)
                result = {'writes': 0, 'archive_created': False, 'reset_tables': {t: meta['fingerprints'][t]['count'] for t in ARCHIVE_TABLES},
                          'protected_tables': list(PROTECTED_TABLES), 'reset_authorized': False}
            elif args.action == 'inspect':
                state, meta = run(c, args.batch)
                if state != 'PREPARING':
                    verify_archive(c, meta)
                result = {'batch': args.batch, 'status': state, 'reset_confirmation': meta['confirmation'],
                          'roster_import_status': meta.get('roster_import', {}).get('status', 'NOT_IMPORTED'),
                          'counts': {t: meta['fingerprints'][t]['count'] for t in ARCHIVE_TABLES}, 'writes': 0}
            else:
                stopped(c)
                if args.action == 'archive':
                    result = prepare(c, args.batch, args.operator)
                elif args.action == 'resume-archive':
                    result = archive(c, args.batch)
                elif args.action == 'rehearse':
                    result = rehearse(c, args.batch)
                elif args.action in ('reset', 'restore'):
                    result = mutate(c, args.batch, args.confirmation, args.action == 'restore')
                else:
                    _, meta = run(c, args.batch)
                    restore_guards(c, meta)
                    result = {'guards_restored': True, 'business_data_changed': False}
                # Publish the final journal/data transaction before releasing the
                # session-scoped maintenance lock to another operator.
                c.commit()
        print(json.dumps(result, indent=2))
    except ServiceError as error:
        print(json.dumps({'error': error.code, 'message': error.message, 'keep_services_stopped': True}), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({'error': 'ROSTER_RECOVERY_REQUIRED', 'message': 'Inspect the batch and guard states before retrying. Do not remove retained archives.', 'keep_services_stopped': True}), file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
