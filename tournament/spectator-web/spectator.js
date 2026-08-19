'use strict';

/* global document, EventSource, location, Replays, window */

function protocolGeneration(presentation) {
	const generation = presentation?.protocol_generation;
	return Number.isSafeInteger(generation) && generation >= 0 ? generation : null;
}

function rendererNeedsReload(currentGeneration, presentation) {
	const nextGeneration = protocolGeneration(presentation);
	return nextGeneration !== null && currentGeneration !== null && nextGeneration !== currentGeneration;
}

function battleScale(width) {
	return Math.max(0.1, width / 640);
}

if (typeof module !== 'undefined' && module.exports) {
	module.exports = { battleScale, protocolGeneration, rendererNeedsReload };
}

(function () {
	if (typeof document === 'undefined') return;
	const config = JSON.parse(document.getElementById('spectator-config').textContent);
	const elements = Object.fromEntries([
		'event-title', 'event-subtitle', 'p1-name', 'p2-name', 'stage-label', 'turn-label', 'connection-label',
		'idle-title', 'idle-subtitle', 'idle-next', 'intro-stage', 'intro-p1', 'intro-p2', 'intro-score',
		'live-score', 'result-stage', 'result-copy', 'result-score', 'standings-stage', 'standings-body',
		'next-match', 'between-score', 'champion-name', 'champion-score', 'champion-note', 'renderer-warning',
	].map(id => [id, document.getElementById(id)]));
	let battle;
	let sequence = config.sequence;
	let rendererGeneration = protocolGeneration(config.presentation);
	let rendererGameID = config.presentation?.game_id || null;

	function text(id, value) {
		elements[id].textContent = value == null ? '' : String(value);
	}

	function participantName(participant, fallback) {
		return participant?.name || fallback;
	}

	function scoreText(presentation) {
		if (!presentation?.series_score) return '';
		const names = new Map([
			[presentation.p1?.id, participantName(presentation.p1, presentation.p1?.id)],
			[presentation.p2?.id, participantName(presentation.p2, presentation.p2?.id)],
			[presentation.winner?.id, participantName(presentation.winner, presentation.winner?.id)],
		]);
		return Object.entries(presentation.series_score).map(([id, score]) => `${names.get(id) || id} ${score}`).join('  ·  ');
	}

	function nextText(next) {
		return next ? `${participantName(next.p1, 'TBD')}  vs  ${participantName(next.p2, 'TBD')}` : 'To be announced';
	}

	function renderStandings(rows) {
		elements['standings-body'].replaceChildren();
		for (const row of rows || []) {
			const tr = document.createElement('tr');
			for (const value of [row.rank, row.name, row.wins, row.losses, row.ties, row.points]) {
				const td = document.createElement('td');
				td.textContent = String(value);
				tr.appendChild(td);
			}
			elements['standings-body'].appendChild(tr);
		}
	}

	function sizeBattleRenderer() {
		const wrapper = document.querySelector('.replay-wrapper');
		if (!wrapper?.clientWidth) return;
		wrapper.style.setProperty('--battle-scale', String(battleScale(wrapper.clientWidth)));
	}

	function updateShell() {
		const state = config.presentation || {};
		document.body.dataset.state = state.kind || 'idle';
		text('event-title', state.title || 'Pokemon Bot Tournament');
		text('event-subtitle', state.subtitle || '');
		text('stage-label', state.stage_label || '');
		text('p1-name', participantName(state.p1, 'Player 1'));
		text('p2-name', participantName(state.p2, 'Player 2'));
		text('idle-title', state.title || 'Pokemon Bot Tournament');
		text('idle-subtitle', state.subtitle || '');
		text('idle-next', state.next_match ? `Next: ${nextText(state.next_match)}` : state.message || 'Tournament ready');
		text('intro-stage', `${state.stage_label || ''}${state.game_number ? ` · Game ${state.game_number}` : ''}`);
		text('intro-p1', participantName(state.p1, 'Player 1'));
		text('intro-p2', participantName(state.p2, 'Player 2'));
		text('intro-score', scoreText(state));
		text('live-score', scoreText(state));
		text('result-stage', state.stage_label || 'Game Result');
		text('result-copy', state.tie ? 'Battle tied' : state.winner ? `${state.winner.name} wins` : 'Game complete');
		text('result-score', scoreText(state));
		text('standings-stage', state.stage_label || 'Standings');
		text('next-match', nextText(state.next_match));
		text('between-score', scoreText(state));
		text('champion-name', participantName(state.winner, 'Champion'));
		text('champion-score', scoreText(state));
		text('champion-note', state.champion_reason === 'tie_safety_limit' ? 'Final tie safety limit reached · top qualifier advances' : 'Congratulations');
		renderStandings(state.standings);
		if (battle) text('turn-label', battle.turn > 0 ? `Turn ${battle.turn}` : 'Team Preview');
	}

	async function refreshState() {
		try {
			const response = await fetch('/api/spectator');
			const state = await response.json();
			if (state.presentation) config.presentation = state.presentation;
			config.complete = state.complete;
			updateShell();
		} catch {}
	}

	function acceptPresentation(presentation) {
		const enteringLive = presentation.kind === 'live';
		if (rendererNeedsReload(rendererGeneration, presentation) || (
			enteringLive && rendererGeneration === null && rendererGameID && presentation.game_id !== rendererGameID
		)) {
			location.reload();
			return;
		}
		rendererGeneration = protocolGeneration(presentation) ?? rendererGeneration;
		if (presentation.game_id) rendererGameID = presentation.game_id;
		config.presentation = presentation;
		updateShell();
		if (enteringLive) window.setTimeout(sizeBattleRenderer, 0);
		if (enteringLive && battle?.paused) battle.play();
	}

	function connect() {
		const events = new EventSource(`/events?after=${sequence}`);
		events.addEventListener('open', () => text('connection-label', 'Live'));
		events.addEventListener('protocol', event => {
			const entry = JSON.parse(event.data);
			if (entry.sequence <= sequence) return;
			sequence = entry.sequence;
			const chunk = entry.chunk || '';
			for (const line of chunk.split('\n')) if (line && battle) battle.add(line);
			if (battle?.paused && config.presentation?.kind === 'live') battle.play();
			updateShell();
		});
		events.addEventListener('presentation', event => {
			const entry = JSON.parse(event.data);
			if (entry.sequence <= sequence) return;
			sequence = entry.sequence;
			if (entry.presentation) acceptPresentation(entry.presentation);
		});
		events.addEventListener('complete', () => {
			text('connection-label', 'Complete');
			void refreshState();
		});
		events.addEventListener('error', () => text('connection-label', config.complete ? 'Complete' : 'Reconnecting'));
	}

	let attachAttempts = 0;
	function attach() {
		if (typeof Replays === 'undefined' || !Replays.battle) {
			attachAttempts++;
			if (attachAttempts === 200) text('renderer-warning', 'Official Showdown renderer unavailable. Check the event preflight and internet connection.');
			return window.setTimeout(attach, 50);
		}
		battle = Replays.battle;
		const officialSubscription = battle.subscription;
		battle.subscribe(state => {
			officialSubscription?.(state);
			updateShell();
			if (state === 'ended') void refreshState();
		});
		Replays.changeSetting('speed', 'fast');
		sizeBattleRenderer();
		updateShell();
		if (config.presentation?.kind === 'live') battle.play();
		if (config.mode !== 'replay') connect();
		else text('connection-label', 'Saved replay');
	}

	updateShell();
	window.addEventListener('resize', sizeBattleRenderer);
	window.addEventListener('load', attach);
})();
