#!/usr/bin/env node
'use strict';

// Installs this skill into the user's Claude skills directory. Copies files
// and nothing else: it does not run the skill and touches nothing outside
// ~/.claude (or the --dest you give it).

const fs = require('fs');
const os = require('os');
const path = require('path');

const pkg = require('../package.json');
const SKILL = pkg.name;
const src = path.resolve(__dirname, '..');
const REQUIRED = ['SKILL.md', 'scripts'];
const OPTIONAL = ['references', 'templates', 'examples', '.living', 'requirements.txt'];
const PARTS = REQUIRED.concat(OPTIONAL.filter((p) => fs.existsSync(path.join(src, p))));

const argv = process.argv.slice(2);
const has = (f) => argv.includes(f);
const dryRun = has('--dry-run') || has('-n');

if (has('--help') || has('-h')) {
  console.log(`
  ${SKILL} — installer

  Usage
    npx ${SKILL} [options]

  Options
    -n, --dry-run   Show what would be written, change nothing
        --dest DIR  Install to DIR instead of ~/.claude/skills/${SKILL}
    -h, --help      This

  Copies the skill's files into your Claude skills directory. An existing
  install is moved to ~/.claude/skill-backups/ first: never overwritten, and
  never left inside skills/, where a backup would register as a second skill.
`);
  process.exit(0);
}

const fail = (msg) => {
  console.error(`  ${msg}`);
  console.error('  Nothing was changed.\n');
  process.exit(1);
};

const known = new Set(['--dry-run', '-n', '--dest']);
const destFlag = argv.indexOf('--dest');
if (destFlag !== -1 && (!argv[destFlag + 1] || argv[destFlag + 1].startsWith('-'))) {
  fail('--dest needs a directory.');
}
const unknown = argv.filter((a, i) => !known.has(a) && i !== destFlag + 1);
if (unknown.length) fail(`Unknown option ${unknown[0]}; see --help.`);

const home = os.homedir();
const dest = destFlag !== -1
  ? path.resolve(argv[destFlag + 1])
  : path.join(home, '.claude', 'skills', SKILL);
const backupRoot = path.join(home, '.claude', 'skill-backups');

// An existing dest is moved to the backups, so it must be a directory this
// installer owns: never home, a skills root, the package itself, or a
// folder holding anything other than this skill.
const inside = (child, parent) => {
  const rel = path.relative(parent, child);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
};
const protectedDirs = [path.parse(dest).root, home, path.join(home, '.claude'),
  path.join(home, '.claude', 'skills'), backupRoot];
if (protectedDirs.includes(dest)) fail(`Refusing to install into ${dest}: pick a folder for this skill.`);
if (inside(dest, src) || inside(src, dest)) fail(`Refusing to install into ${dest}: it overlaps the package.`);

const skillName = (dir) => {
  try {
    const head = fs.readFileSync(path.join(dir, 'SKILL.md'), 'utf8').split(/^---$/m)[1] || '';
    const m = head.match(/^name:\s*(\S+)\s*$/m);
    return m ? m[1] : null;
  } catch (e) {
    return null;
  }
};
let existing = false;
if (fs.existsSync(dest)) {
  if (!fs.statSync(dest).isDirectory()) fail(`Refusing to install: ${dest} is a file.`);
  const entries = fs.readdirSync(dest).filter((f) => f !== '.DS_Store');
  if (entries.length && skillName(dest) !== SKILL) {
    fail(`Refusing to install: ${dest} exists and is not a ${SKILL} install.`);
  }
  existing = entries.length > 0;
}

const say = (s) => console.log(s);
const tick = (s) => say(`  ✓ ${s}`);

say(`\n  ${SKILL} v${pkg.version}`);
say(`  from ${src}`);
say(`  to   ${dest}${dryRun ? '   (dry run)' : ''}\n`);

// Refuse to run from a tree that is missing its own content, which would
// otherwise install a hollow skill over a working one.
const missing = REQUIRED.filter((p) => !fs.existsSync(path.join(src, p)));
if (missing.length) {
  console.error(`  Cannot install: this package is missing ${missing.join(', ')}.`);
  console.error('  Nothing was changed.\n');
  process.exit(1);
}

// Back up any existing install. Backups go OUTSIDE skills/ deliberately:
// anything with a SKILL.md under skills/ is discovered as a skill.
if (existing) {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '').replace('T', '-');
  const backup = path.join(backupRoot, `${SKILL}-${stamp}`);
  if (dryRun) {
    tick(`would back up existing install to ${backup}`);
  } else {
    fs.mkdirSync(backupRoot, { recursive: true });
    fs.renameSync(dest, backup);
    tick(`backed up existing install to ${backup}`);
  }
}

if (!dryRun) fs.mkdirSync(dest, { recursive: true });

const skip = (p) => !/__pycache__|\.DS_Store|\.pyc$/.test(p);
for (const part of PARTS) {
  const from = path.join(src, part);
  const to = path.join(dest, part);
  if (dryRun) {
    const st = fs.statSync(from);
    tick(`would copy ${part}${st.isDirectory() ? ` (${fs.readdirSync(from).filter(skip).length} entries)` : ''}`);
    continue;
  }
  fs.cpSync(from, to, { recursive: true, filter: skip });
  tick(`copied ${part}`);
}

// The scripts run as `python3 scripts/<name>.py`; the bit is a courtesy.
if (!dryRun) {
  const scripts = path.join(dest, 'scripts');
  for (const f of fs.readdirSync(scripts)) {
    if (/\.(py|sh)$/.test(f)) fs.chmodSync(path.join(scripts, f), 0o755);
  }
  tick('made scripts executable');
}

say(dryRun ? `
  Dry run. Nothing was written.
` : `
  Done. Restart Claude Code, then say "put my app on the App Store", "ship an update" or "add German".
  The scripts need Python 3.10+ with Pillow and PyYAML:  python3 -m pip install -r ${path.join(dest, 'requirements.txt')}
  For the App Store Connect API, create a Team key (App Manager) once; the skill walks you through it.
`);
