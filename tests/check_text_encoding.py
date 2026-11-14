"""Check public source encoding without rejecting valid Unicode or user data.

Default scope is Git's public source inventory. A release/build inventory can
instead be supplied with --paths-file (UTF-8 relative paths, one per line).
"""
from pathlib import Path
import argparse
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
TEXT_EXTENSIONS={'.py','.js','.mjs','.html','.css','.md','.json','.ps1','.cs','.cmd','.nsi','.txt','.yml','.yaml'}
MOJIBAKE=re.compile(
    '[\ufffd]|[\u00c2\u00c3][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013-\u2026\u2030\u2039\u203a\u20ac\u2122]'
    '|\u00e2[\u0080\u20ac]|\u00f0\u0178|\u00ef\u00bf\u00bd')


def check_text(text):
    return [number for number,line in enumerate(text.splitlines(),1) if MOJIBAKE.search(line)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paths-file',type=Path)
    args=parser.parse_args()
    # French accents, punctuation, multiplication signs and emoji are valid.
    assert not check_text('Déjà prêt — modèle · animation… 2 × 3 🎬')
    assert check_text('Orbit \u00c2\u00b7 View')==[1]
    assert check_text('Range 1\u00e2\u20ac\u201c100')==[1]
    assert check_text('Broken \ufffd')==[1]
    if args.paths_file:
        paths=args.paths_file.read_text(encoding='utf-8-sig').splitlines()
    else:
        paths=subprocess.check_output(['git','-C',str(ROOT),'-c','core.quotePath=false',
            'ls-files','--cached','--others','--exclude-standard','-z']).decode('utf-8').split('\0')
    count=0;errors=[]
    for name in sorted(set(paths)):
        if not name:continue
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            errors.append((name,'unsafe inventory path'));continue
        path=ROOT/relative
        if path.suffix.lower() not in TEXT_EXTENSIONS or not path.is_file():continue
        count+=1
        try:text=path.read_text(encoding='utf-8-sig')
        except UnicodeError:
            errors.append((name,'not valid UTF-8'));continue
        for line in check_text(text):errors.append((name,'possible mojibake on line '+str(line)))
    for name,message in errors:print(name+': '+message)
    if errors:raise SystemExit('Public text encoding check failed.')
    print(f'Public text encoding check passed: {count} text files; valid Unicode is allowed.')


if __name__=='__main__':main()
