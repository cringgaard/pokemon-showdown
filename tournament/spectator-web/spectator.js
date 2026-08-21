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

function playbackAcknowledgementGeneration(mode, presentation, rendererState, activeGeneration = null) {
	if (mode !== 'event' || rendererState !== 'ended') return null;
	if (presentation?.kind === 'live') return protocolGeneration(presentation);
	return Number.isSafeInteger(activeGeneration) && activeGeneration >= 0 ? activeGeneration : null;
}

function playbackControlIsCurrent(rendererGeneration, currentVersion, playback) {
	return playback && playback.protocol_generation === rendererGeneration &&
		Number.isSafeInteger(playback.version) && playback.version > currentVersion;
}

if (typeof module !== 'undefined' && module.exports) {
	module.exports = {
		battleScale, playbackAcknowledgementGeneration, playbackControlIsCurrent,
		protocolGeneration, rendererNeedsReload,
	};
}

(function () {
	if (typeof document === 'undefined') return;
	const config = JSON.parse(document.getElementById('spectator-config').textContent);
	const elements = Object.fromEntries([
		'event-title', 'event-subtitle', 'p1-name', 'p2-name', 'stage-label', 'turn-label', 'connection-label',
		'idle-title', 'idle-subtitle', 'idle-next', 'intro-stage', 'intro-p1', 'intro-p2', 'intro-score',
		'live-score', 'result-stage', 'result-copy', 'result-score', 'standings-stage', 'standings-body',
		'next-match', 'between-score', 'champion-name', 'champion-score', 'champion-note', 'renderer-warning',
		'team-sheet-name', 'team-sheet-grid', 'preview-p1-name', 'preview-p2-name',
		'preview-p1-roster', 'preview-p2-roster', 'preview-status-title',
	].map(id => [id, document.getElementById(id)]));
	let battle;
	let sequence = config.sequence;
	let rendererGeneration = protocolGeneration(config.presentation);
	let rendererGameID = config.presentation?.game_id || null;
	let livePlaybackGeneration = Number.isSafeInteger(config.playback?.protocol_generation) ?
		config.playback.protocol_generation : (config.presentation?.kind === 'live' ? rendererGeneration : null);
	const acknowledgedGenerations = new Set();
	const acknowledgementInFlight = new Set();
	let playbackVersion = -1;

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

	function pokemonImage(pokemon) {
		const image = document.createElement('img');
		image.src = `https://play.pokemonshowdown.com/sprites/gen5/${encodeURIComponent(pokemon.sprite)}.png`;
		image.alt = '';
		return image;
	}

	function renderTeamCard(pokemon) {
		const card = document.createElement('article');
		card.className = 'team-card';
		const top = document.createElement('div');
		top.className = 'team-card-top';
		top.appendChild(pokemonImage(pokemon));
		const heading = document.createElement('h2');
		heading.textContent = pokemon.name === pokemon.species ? pokemon.species : `${pokemon.name} (${pokemon.species})`;
		top.appendChild(heading);
		card.appendChild(top);
		const facts = document.createElement('div');
		facts.className = 'team-card-facts';
		for (const [label, value] of [['Ability', pokemon.ability], ['Item', pokemon.item || 'No item']]) {
			const row = document.createElement('div');
			const key = document.createElement('span');
			key.textContent = label;
			const detail = document.createElement('strong');
			detail.textContent = value;
			row.append(key, detail);
			facts.appendChild(row);
		}
		card.appendChild(facts);
		const moves = document.createElement('ul');
		for (const move of pokemon.moves) {
			const item = document.createElement('li');
			item.textContent = move;
			moves.appendChild(item);
		}
		card.appendChild(moves);
		return card;
	}

	function renderTeamSheet(team) {
		text('team-sheet-name', team?.participant?.name || 'Team');
		elements['team-sheet-grid'].replaceChildren(...(team?.pokemon || []).map(renderTeamCard));
	}

	function renderPreviewSide(side, team) {
		text(`preview-${side}-name`, team?.participant?.name || side.toUpperCase());
		const roster = elements[`preview-${side}-roster`];
		roster.replaceChildren(...(team?.pokemon || []).map(pokemon => {
			const tile = document.createElement('div');
			tile.className = 'preview-pokemon';
			tile.appendChild(pokemonImage(pokemon));
			const name = document.createElement('strong');
			name.textContent = pokemon.species;
			tile.appendChild(name);
			return tile;
		}));
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
		const sheet = state.team_sheet_side && state.teams?.[state.team_sheet_side];
		if (sheet) renderTeamSheet(sheet);
		renderPreviewSide('p1', state.teams?.p1);
		renderPreviewSide('p2', state.teams?.p2);
		text('preview-status-title', state.kind === 'selection_locked' ? 'Selection locked' : 'Selecting teams...');
		text('champion-note', state.champion_reason === 'tie_safety_limit' ? 'Final tie safety limit reached · top qualifier advances' : 'Congratulations');
		renderStandings(state.standings);
		if (battle) text('turn-label', battle.turn > 0 ? `Turn ${battle.turn}` : 'Team Preview');
	}

	function applyPlayback(playback, force = false) {
		if (!battle || !playback) return;
		if (!force && !playbackControlIsCurrent(rendererGeneration, playbackVersion, playback)) return;
		if (playback.protocol_generation !== rendererGeneration) return;
		playbackVersion = playback.version;
		config.playback = playback;
		Replays.changeSetting('speed', playback.speed);
		if (playback.paused) Replays.pause();
		else if (config.presentation?.kind === 'live') Replays.play();
	}

	async function refreshState() {
		try {
			const response = await fetch('/api/spectator');
			const state = await response.json();
			if (state.presentation) config.presentation = state.presentation;
			if (state.playback) applyPlayback(state.playback);
			config.complete = state.complete;
			updateShell();
		} catch {}
	}

	async function acknowledgePlayback(rendererState) {
		const generation = playbackAcknowledgementGeneration(
			config.mode, config.presentation, rendererState, livePlaybackGeneration
		);
		if (generation === null || acknowledgedGenerations.has(generation) || acknowledgementInFlight.has(generation)) return;
		acknowledgementInFlight.add(generation);
		while (!acknowledgedGenerations.has(generation)) {
			try {
				const response = await fetch('/api/playback-complete', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ protocol_generation: generation }),
					keepalive: true,
				});
				if (!response.ok) throw new Error(`Playback acknowledgement failed: ${response.status}`);
				acknowledgedGenerations.add(generation);
				break;
			} catch {
				if (config.playback?.protocol_generation !== generation && (
					config.presentation?.kind !== 'live' || protocolGeneration(config.presentation) !== generation
				)) break;
				await new Promise(resolve => { window.setTimeout(resolve, 1000); });
			}
		}
		acknowledgementInFlight.delete(generation);
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
		if (enteringLive) livePlaybackGeneration = protocolGeneration(presentation);
		updateShell();
		if (enteringLive) window.setTimeout(sizeBattleRenderer, 0);
		if (enteringLive) applyPlayback(config.playback, true);
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
			if (battle?.paused && config.presentation?.kind === 'live' && !config.playback?.paused) battle.play();
			updateShell();
		});
		events.addEventListener('presentation', event => {
			const entry = JSON.parse(event.data);
			if (entry.sequence <= sequence) return;
			sequence = entry.sequence;
			if (entry.presentation) acceptPresentation(entry.presentation);
		});
		events.addEventListener('playback', event => applyPlayback(JSON.parse(event.data)));
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
			if (state === 'ended') {
				void acknowledgePlayback(state);
				void refreshState();
			}
		});
		applyPlayback(config.playback, true);
		sizeBattleRenderer();
		updateShell();
		if (config.presentation?.kind === 'live' && !config.playback?.paused) battle.play();
		if (config.mode !== 'replay') connect();
		else text('connection-label', 'Saved replay');
	}

	updateShell();
	window.addEventListener('resize', sizeBattleRenderer);
	window.addEventListener('load', attach);
})();
