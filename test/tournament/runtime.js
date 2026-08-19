'use strict';

const path = require('path');
const assert = require('../assert');
const { BotController } = require('../../dist/tournament/bots/runtime');
const {
	DEFAULT_MAX_STDERR_BYTES, STDERR_TRUNCATION_MARKER,
} = require('../../dist/tournament/bots/jsonl-worker');

const legalActions = [
	{ team: ['team_0', 'team_1', 'team_2', 'team_3'] },
	{ team: ['team_3', 'team_2', 'team_1', 'team_0'] },
];

function state(runtime) {
	return {
		schema_version: 1,
		battle: { format: 'test', turn: 0, phase: 'team_preview' },
		runtime,
		self: { name: 'Bot', team: [], active: {}, side_conditions: {} },
		opponent: { name: 'Foe', team: [], active: {}, side_conditions: {} },
		field: { weather: null, weather_started_turn: null, conditions: {} },
		request: { kind: 'team_preview', team_size: 4, legal_actions: legalActions },
		history: [],
	};
}

function controller(name, options = {}) {
	return new BotController(path.resolve(__dirname, 'fixtures', `${name}.py`), {
		fallbackKey: 'fixed-test-seed:p1',
		decisionTimeoutMs: 1000,
		maxInvalidAttempts: 3,
		...options,
	});
}

function decide(bot, overrides = {}) {
	return bot.decide({
		decisionID: 7,
		revision: 0,
		deadlineAt: Date.now() + 2000,
		newDecision: true,
		buildState: state,
		...overrides,
	});
}

describe('Tournament Python runtime supervision', () => {
	it('uses persistent JSONL and prevents participant stdout from corrupting it', async () => {
		const bot = controller('noisy');
		try {
			assert.deepEqual(await decide(bot), legalActions[0]);
			assert.equal(bot.stats.fallbacks, 0);
		} finally {
			await bot.stop();
		}
	});

	it('allows invalid retries and accepts a later valid response', async () => {
		const bot = controller('fail_twice');
		try {
			assert.deepEqual(await decide(bot), legalActions[0]);
			assert.equal(bot.stats.invalid_responses, 2);
			assert.equal(bot.stats.fallbacks, 0);
		} finally {
			await bot.stop();
		}
	});

	it('falls back deterministically after repeated illegal responses', async () => {
		const first = controller('invalid');
		const second = controller('invalid');
		try {
			const [a, b] = await Promise.all([decide(first), decide(second)]);
			assert.deepEqual(a, b);
			assert(legalActions.some(action => JSON.stringify(action) === JSON.stringify(a)));
			assert.equal(first.stats.invalid_responses, 3);
			assert.equal(first.stats.fallbacks, 1);
		} finally {
			await Promise.all([first.stop(), second.stop()]);
		}
	});

	it('serializes exceptions and falls back without deadlocking', async () => {
		const bot = controller('exception');
		try {
			await decide(bot);
			assert.equal(bot.stats.exceptions, 3);
			assert.equal(bot.stats.fallbacks, 1);
		} finally {
			await bot.stop();
		}
	});

	it('kills a hanging worker, falls back, and can restart next decision', async () => {
		const bot = controller('hang_decision', { decisionTimeoutMs: 100 });
		try {
			const started = Date.now();
			await decide(bot, { deadlineAt: Date.now() + 100 });
			assert(Date.now() - started < 1000);
			assert.equal(bot.stats.timeouts, 1);
			assert.equal(bot.stats.fallbacks, 1);
			assert.deepEqual(await decide(bot, {
				decisionID: 8,
				deadlineAt: Date.now() + 1000,
			}), legalActions[0]);
		} finally {
			await bot.stop();
		}
	});

	it('terminates oversized JSONL without retaining an unbounded stdout buffer', async () => {
		const bot = controller('oversized_stdout', {
			decisionTimeoutMs: 1000,
			maxProtocolLineBytes: 4096,
		});
		try {
			const response = await decide(bot);
			assert(legalActions.some(action => JSON.stringify(action) === JSON.stringify(response)));
			assert(bot.stats.exceptions > 0);
			assert.equal(bot.stats.fallbacks, 1);
		} finally {
			await bot.stop();
		}
	});

	it('bounds excessive participant stderr and records a truncation marker', async () => {
		const bot = controller('excessive_stderr', { maxStderrBytes: 1024 });
		try {
			assert.deepEqual(await decide(bot), legalActions[0]);
			const stderr = bot.stderr();
			assert(stderr.includes(STDERR_TRUNCATION_MARKER));
			assert(Buffer.byteLength(stderr.join('')) <= 1024 + Buffer.byteLength(STDERR_TRUNCATION_MARKER));
			assert(DEFAULT_MAX_STDERR_BYTES >= 1024);
		} finally {
			await bot.stop();
		}
	});
});
