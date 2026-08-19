import * as fs from 'fs';
import * as path from 'path';
import { Dex } from '../../sim/dex';
import { Teams } from '../../sim/teams';
import { TeamValidator } from '../../sim/team-validator';

export const TOURNAMENT_TEAM_SIZE = 6;

export class SubmissionValidationError extends Error {
	override name = 'SubmissionValidationError';
}

export interface ValidatedTeam {
	teamText: string;
	packedTeam: string;
}

export interface LoadedSubmission extends ValidatedTeam {
	id: string;
	name: string;
	directory: string;
	mainPath: string;
	requirementsPath: string | null;
}

export interface LoadSubmissionOptions {
	format: string;
	name?: string;
	expectedTeamSize?: number;
}

export function loadSubmission(directory: string, options: LoadSubmissionOptions): LoadedSubmission {
	Dex.includeData();
	const resolvedDirectory = path.resolve(directory);
	assertDirectory(resolvedDirectory);
	const mainPath = requiredFile(resolvedDirectory, 'main.py');
	const teamPath = requiredFile(resolvedDirectory, 'team.txt');
	let teamText: string;
	try {
		teamText = fs.readFileSync(teamPath, 'utf8');
	} catch (error) {
		throw new SubmissionValidationError(
			`Cannot read team.txt in submission ${quote(resolvedDirectory)}: ${errorMessage(error)}`
		);
	}
	const name = options.name || path.basename(resolvedDirectory);
	const validated = validateTeamExport(teamText, options.format, name, options.expectedTeamSize);
	const requirements = path.join(resolvedDirectory, 'requirements.txt');
	return {
		id: submissionID(name),
		name,
		directory: resolvedDirectory,
		mainPath,
		requirementsPath: isFile(requirements) ? requirements : null,
		...validated,
	};
}

export function validateTeamExport(
	teamText: string, format: string, participantName: string, expectedTeamSize = TOURNAMENT_TEAM_SIZE
): ValidatedTeam {
	Dex.includeData();
	let team;
	try {
		team = Teams.import(teamText);
	} catch (error) {
		throw new SubmissionValidationError(
			`${participantName}'s team.txt could not be imported: ${errorMessage(error)}`
		);
	}
	if (!team?.length) {
		throw new SubmissionValidationError(
			`${participantName}'s team.txt could not be imported as a Pokemon Showdown team export.`
		);
	}
	if (team.length !== expectedTeamSize) {
		throw new SubmissionValidationError(
			`${participantName}'s team must contain exactly ${expectedTeamSize} Pokemon; found ${team.length}.`
		);
	}
	let problems: string[] | null;
	try {
		problems = TeamValidator.get(format).validateTeam(team);
	} catch (error) {
		throw new SubmissionValidationError(
			`Could not validate ${participantName}'s team for format ${quote(format)}: ${errorMessage(error)}`
		);
	}
	if (problems?.length) {
		throw new SubmissionValidationError(
			`${participantName}'s team is invalid for ${format}:\n- ${problems.join('\n- ')}`
		);
	}
	return { teamText, packedTeam: Teams.pack(team) };
}

function assertDirectory(directory: string) {
	let stat: fs.Stats;
	try {
		stat = fs.statSync(directory);
	} catch (error) {
		throw new SubmissionValidationError(`Submission directory ${quote(directory)} does not exist or is inaccessible: ${errorMessage(error)}`);
	}
	if (!stat.isDirectory()) throw new SubmissionValidationError(`Submission path ${quote(directory)} is not a directory.`);
}

function requiredFile(directory: string, filename: string) {
	const filepath = path.join(directory, filename);
	if (!isFile(filepath)) {
		throw new SubmissionValidationError(`Submission ${quote(directory)} is missing required file ${filename}.`);
	}
	return filepath;
}

function isFile(filepath: string) {
	try {
		return fs.statSync(filepath).isFile();
	} catch {
		return false;
	}
}

function submissionID(name: string) {
	return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'participant';
}

function quote(value: string) {
	return JSON.stringify(value);
}

function errorMessage(error: unknown) {
	return error instanceof Error ? error.message : String(error);
}
