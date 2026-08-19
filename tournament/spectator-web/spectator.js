'use strict';

/* global document, EventSource, Replays, window */

(function () {
	const config = JSON.parse(document.getElementById('spectator-config').textContent);
	const p1Name = document.getElementById('p1-name');
	const p2Name = document.getElementById('p2-name');
	const turnLabel = document.getElementById('turn-label');
	const formatLabel = document.getElementById('format-label');
	const connectionLabel = document.getElementById('connection-label');
	const resultBanner = document.getElementById('result-banner');
	let battle;
	let sequence = config.sequence;

	function participant(side) {
		return config.metadata?.participants?.[side]?.name || side.toUpperCase();
	}

	function updateShell() {
		p1Name.textContent = participant('p1');
		p2Name.textContent = participant('p2');
		formatLabel.textContent = config.metadata?.format || '';
		if (battle) turnLabel.textContent = battle.turn > 0 ? `Turn ${battle.turn}` : 'Team Preview';
		const result = config.result;
		if (result?.tie) resultBanner.textContent = 'Battle ended in a tie';
		else if (result?.winner) resultBanner.textContent = `${result.winner} wins!`;
	}

	async function refreshResult() {
		try {
			const response = await fetch('/api/spectator');
			const state = await response.json();
			config.result = state.result;
			config.complete = state.complete;
			updateShell();
		} catch {}
	}

	function connectLive() {
		const events = new EventSource(`/events?after=${sequence}`);
		events.addEventListener('open', () => {
			connectionLabel.textContent = 'Live';
		});
		events.addEventListener('protocol', event => {
			const entry = JSON.parse(event.data);
			if (entry.sequence <= sequence) return;
			sequence = entry.sequence;
			for (const line of entry.chunk.split('\n')) {
				if (line) battle.add(line);
			}
			if (battle.paused) battle.play();
			updateShell();
		});
		events.addEventListener('complete', () => {
			connectionLabel.textContent = 'Complete';
			void refreshResult();
		});
		events.addEventListener('error', () => {
			connectionLabel.textContent = config.complete ? 'Complete' : 'Reconnecting...';
		});
	}

	function attach() {
		if (typeof Replays === 'undefined' || !Replays.battle) return setTimeout(attach, 25);
		battle = Replays.battle;
		const officialSubscription = battle.subscription;
		battle.subscribe(state => {
			officialSubscription?.(state);
			updateShell();
			if (state === 'ended') void refreshResult();
		});
		updateShell();
		if (config.mode === 'live') {
			Replays.changeSetting('speed', 'fast');
			battle.play();
			connectLive();
		} else {
			connectionLabel.textContent = 'Saved replay';
		}
	}

	window.addEventListener('load', attach);
})();
