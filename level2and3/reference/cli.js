#!/usr/bin/env node
'use strict';
// identity-verify — local OS identity + group check. No network calls, no process spawning.
// Usage: cli.js [--json] [--expect profile.json]
//   report mode exits 0; verify mode exits 0 pass / 1 mismatch / 2 error.

const os = require('os');
const fs = require('fs');
const isWin = process.platform === 'win32';

function readFileSafe(p) {
    try { return fs.readFileSync(p, 'utf8'); } catch { return ''; }
}

// POSIX group membership straight from /etc/group + the user's primary gid.
// No process spawn. Covers local groups only (not LDAP/SSSD-provided ones).
function posixGroups(username, primaryGid) {
    const names = new Set();
    for (const line of readFileSafe('/etc/group').split('\n')) {
        if (!line || line[0] === '#') continue;
        const [name, , gid, members] = line.split(':');
        if (!name) continue;
        if (Number(gid) === primaryGid) names.add(name);
        const memberList = (members || '').split(',').map(s => s.trim()).filter(Boolean);
        if (username && memberList.includes(username)) names.add(name);
    }
    return [...names];
}

function identity() {
    const id = { username: null, uid: null, gid: null, groups: [], hostname: os.hostname(), platform: process.platform };
    try {
        const i = os.userInfo();
        id.username = i.username;
        if (typeof i.uid === 'number' && i.uid >= 0) id.uid = i.uid;
        if (typeof i.gid === 'number' && i.gid >= 0) id.gid = i.gid;
    } catch {
        id.username = process.env.USER || process.env.USERNAME || null;
    }
    if (!isWin) id.groups = posixGroups(id.username, id.gid);
    // Windows: no subprocess-free group API in Node; groups left empty (see SKILL.md).
    return id;
}

const eq = (a, b) => isWin ? a.toLowerCase() === b.toLowerCase() : a === b;
const has = (gs, n) => gs.some(g => eq(g, n));

function verify(id, exp) {
    const f = [];
    if (exp.username != null && id.username !== exp.username) f.push(`username "${id.username}" != "${exp.username}"`);
    if (exp.uid != null && id.uid !== exp.uid) f.push(`uid ${id.uid} != ${exp.uid}`);
    if (exp.hostname != null && id.hostname !== exp.hostname) f.push(`hostname "${id.hostname}" != "${exp.hostname}"`);
    for (const g of exp.requiredGroups || []) if (!has(id.groups, g)) f.push(`missing group "${g}"`);
    for (const g of exp.forbiddenGroups || []) if (has(id.groups, g)) f.push(`forbidden group "${g}"`);
    return { pass: f.length === 0, failures: f };
}

function report(id) {
    console.log(`username : ${id.username ?? '(unknown)'}`);
    if (id.uid !== null) console.log(`uid      : ${id.uid}`);
    if (id.gid !== null) console.log(`gid      : ${id.gid}`);
    console.log(`hostname : ${id.hostname}`);
    console.log(`platform : ${id.platform}`);
    console.log(`groups   : ${id.groups.join(', ') || '(none found)'}`);
}

const args = process.argv.slice(2);
const json = args.includes('--json');
const ei = args.indexOf('--expect');
const id = identity();

if (ei === -1) {
    if (json) console.log(JSON.stringify(id, null, 2));
    else report(id);
    process.exit(0);
}

const path = args[ei + 1];
if (!path) { console.error('error: --expect needs a profile path'); process.exit(2); }

let exp;
try { exp = JSON.parse(fs.readFileSync(path, 'utf8')); }
catch (e) { console.error(`error: ${e.message}`); process.exit(2); }

const r = verify(id, exp);
if (json) {
    console.log(JSON.stringify({ identity: id, ...r }, null, 2));
} else {
    report(id);
    console.log(r.pass ? 'RESULT   : PASS' : 'RESULT   : FAIL');
    for (const x of r.failures) console.log(`  - ${x}`);
}
process.exit(r.pass ? 0 : 1);
