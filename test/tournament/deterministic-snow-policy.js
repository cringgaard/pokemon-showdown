'use strict';

const path = require('path');
const childProcess = require('child_process');
const assert = require('../assert');

describe('Deterministic snow policy foundations', () => {
	it('pass the focused Python B1 suite', () => {
		const result = childProcess.spawnSync('python', [
			'-m', 'unittest', 'discover',
			'-s', path.resolve(__dirname, 'deterministic-snow'),
			'-p', 'test_*.py',
		], {
			cwd: path.resolve(__dirname, '..', '..'),
			encoding: 'utf8',
			env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
		});
		assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
	});
});
