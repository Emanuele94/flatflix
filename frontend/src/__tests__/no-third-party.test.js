import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const frontendDir = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const srcDir = join(frontendDir, 'src');

function sourceFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    if (name === '__tests__') continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full));
    else out.push(full);
  }
  return out;
}

describe('portal loads nothing from outside its own origin', () => {
  const indexHtml = readFileSync(join(frontendDir, 'index.html'), 'utf8');

  it('index.html and src contain no http(s) URL', () => {
    const offenders = [join(frontendDir, 'index.html'), ...sourceFiles(srcDir)].filter(
      (file) => /https?:\/\//.test(readFileSync(file, 'utf8')),
    );
    expect(offenders).toEqual([]);
  });

  it('index.html is English and mobile-ready', () => {
    expect(indexHtml).toContain('lang="en"');
    expect(indexHtml).toContain('width=device-width');
  });
});
