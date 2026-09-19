import * as core from '@actions/core';
import * as io from '@actions/io';
import * as exec from '@actions/exec';
import { DefaultArtifactClient } from '@actions/artifact';
import * as glob from '@actions/glob';
import fs from 'fs';
import { Octokit } from "@octokit/core";

const TARGET_POLICIES = Object.freeze({
    x64: Object.freeze({
        cacheArtifact: 'build-artifact',
        finalArtifact: 'chromium',
        maximumBuildSeconds: 18900,
        reserveSeconds: 2100,
    }),
    x86: Object.freeze({
        cacheArtifact: 'build-artifact-x86',
        finalArtifact: 'chromium-x86',
        maximumBuildSeconds: 18600,
        reserveSeconds: 2100,
    }),
    arm64: Object.freeze({
        cacheArtifact: 'build-artifact-arm',
        finalArtifact: 'chromium-arm',
        maximumBuildSeconds: 18600,
        reserveSeconds: 2400,
    }),
});

let finishedOutput = false;

function getTargetPolicy(target) {
    if (!Object.hasOwn(TARGET_POLICIES, target)) {
        throw new Error(`Unsupported Windows target ${JSON.stringify(target)}; expected one of: x64, x86, arm64`);
    }

    return TARGET_POLICIES[target];
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function isMountpoint(path) {
    const { exitCode } = await exec.getExecOutput('mountpoint', ['-q', path], { ignoreReturnCode: true });
    return exitCode === 0;
}

async function ensureUnmounted(path) {
    const retryCount = 3;
    const retryDelayMs = 10000;

    console.log('Unmounting ciopfs if mounted...');
    if (!await isMountpoint(path)) {
        console.log(`${path} is not a mountpoint, skipping unmount`);
        return;
    }

    for (let attempt = 1; attempt <= retryCount; attempt++) {
        console.log(`Unmount attempt ${attempt}/${retryCount}: ${path}`);
        const { stdout, stderr } = await exec.getExecOutput('fusermount', ['-u', path], { ignoreReturnCode: true });

        if (stdout.trim()) {
            console.log(stdout.trim());
        }
        if (stderr.trim()) {
            console.error(stderr.trim());
        }

        if (!await isMountpoint(path)) {
            console.log(`Unmount completed on attempt ${attempt}`);
            return;
        }

        console.error(`Mountpoint still active after attempt ${attempt}/${retryCount}: ${path}`);
        if (attempt < retryCount) {
            console.log(`Waiting ${retryDelayMs / 1000} seconds before retrying unmount`);
            await sleep(retryDelayMs);
        }
    }

    throw new Error(`Failed to unmount ciopfs mountpoint after ${retryCount} attempts: ${path}`);
}

async function tryDownloadArtifactWithRetry(artifact, artifactName, downloadPath, messages) {
    const retryCount = 3;
    const retryDelayMs = 10000;

    for (let attempt = 1; attempt <= retryCount; attempt++) {
        try {
            console.log(`${messages.start} (attempt ${attempt}/${retryCount}): ${artifactName}`);

            const artifactInfo = await artifact.getArtifact(artifactName);
            await artifact.downloadArtifact(artifactInfo.artifact.id, { path: downloadPath });

            console.log(`${messages.success}: ${artifactName}`);
            return true;
        } catch (e) {
            console.error(`${messages.failure} (attempt ${attempt}/${retryCount}): ${e}`);
            await sleep(retryDelayMs);
        }
    }

    console.error(messages.stop);
    return false;
}

async function uploadArtifactWithRetry(artifact, name, files, rootDirectory, errorPrefix) {
    const retryCount = 5;
    const retryDelayMs = 10000;
    for (let i = 1; i <= retryCount; ++i) {
        try {
            await artifact.deleteArtifact(name);
        } catch (e) {
            // ignored
        }
        try {
            await artifact.uploadArtifact(name, files, rootDirectory, { retentionDays: 4, compressionLevel: 0 });
            return;
        } catch (e) {
            console.error(`${errorPrefix}: ${e}`);
            await sleep(retryDelayMs);
        }
    }

    throw new Error(`${errorPrefix}: retry limit exceeded`);
}

async function extractArchiveAndDelete(archivePath, destPath) {
    await exec.exec('tar', ['-I', 'zstd -T0', '-xf', archivePath, '-C', destPath]);
    await io.rmRF(archivePath);
}

async function cleanupVsFilesIfPresent(vsFilesPath) {
    if (fs.existsSync(vsFilesPath)) {
        console.log(`Cleaning up ciopfs mountpoint: ${vsFilesPath}`);
        await io.rmRF(vsFilesPath);
    }
}

async function restoreFromArtifacts(artifact, artifactName, archivePath, buildDir, downloadPath) {
    const artifactDownloaded = await tryDownloadArtifactWithRetry(artifact, artifactName, downloadPath, {
        start: 'Downloading artifact',
        success: 'Artifact download complete',
        failure: 'Artifact download failed',
        stop: 'Failed to download artifact after 3 attempts, stopping stage'
    });
    if (!artifactDownloaded) {
        return false;
    }

    await extractArchiveAndDelete(archivePath, buildDir);
    await cleanupVsFilesIfPresent(`${buildDir}/src/third_party/depot_tools/win_toolchain/vs_files`);
    return true;
}

async function getJobTimeInfo(token) {
    if (!token) {
        console.log('No GitHub token provided; skipping job metadata query');
        return null;
    }

    const repository = process.env.GITHUB_REPOSITORY;
    const runId = process.env.GITHUB_RUN_ID;
    const githubJob = process.env.GITHUB_JOB;
    const runnerName = process.env.RUNNER_NAME;

    if (!repository || !runId) {
        console.log('GITHUB_REPOSITORY or GITHUB_RUN_ID not set; skipping job metadata query');
        return null;
    }

    const [owner, repo] = repository.split('/');
    if (!owner || !repo) {
        console.warn(`Invalid GITHUB_REPOSITORY format: ${repository}`);
        return null;
    }

    const octokit = new Octokit({
        auth: token,
        baseUrl: process.env.GITHUB_API_URL || 'https://api.github.com'
    });

    try {
        const response = await octokit.request('GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs', {
            owner,
            repo,
            run_id: Number(runId),
            per_page: 100,
            headers: {
                'X-GitHub-Api-Version': '2026-03-10'
            }
        });

        const jobs = response?.data?.jobs;
        if (!Array.isArray(jobs)) {
            console.warn('Unexpected GitHub API response payload structure');
            return null;
        }

        const runAttemptInput = process.env.GITHUB_RUN_ATTEMPT;
        const runAttempt = runAttemptInput ? Number(runAttemptInput) : null;

        // Find the current job matching in_progress and runner_name / githubJob, respecting run_attempt
        const matchingJob = jobs.find(j => {
            if (j.status !== 'in_progress') return false;
            if (runAttempt && j.run_attempt && j.run_attempt !== runAttempt) return false;
            if (runnerName && j.runner_name === runnerName) return true;
            if (githubJob && (j.name === githubJob || j.name.endsWith(` / ${githubJob}`))) return true;
            return false;
        }) || jobs.find(j => {
            if (runAttempt && j.run_attempt && j.run_attempt !== runAttempt) return false;
            if (githubJob && (j.name === githubJob || j.name.endsWith(` / ${githubJob}`))) return true;
            return false;
        });

        if (!matchingJob || !matchingJob.created_at) {
            console.warn(`Could not locate matching in_progress job metadata for GITHUB_JOB=${githubJob}`);
            return null;
        }

        const createdAtSeconds = Math.floor(new Date(matchingJob.created_at).getTime() / 1000);
        const startedAtSeconds = matchingJob.started_at ? Math.floor(new Date(matchingJob.started_at).getTime() / 1000) : null;
        return {
            createdAt: createdAtSeconds,
            startedAt: startedAtSeconds,
            createdAtISO: matchingJob.created_at,
        };
    } catch (err) {
        console.warn(`Failed to query job metadata: ${err.message}`);
        return null;
    }
}

async function run() {
    process.on('SIGTERM', () => {
        console.error('Received SIGTERM, writing finished output and exiting');
        core.setOutput('finished', finishedOutput);
        process.exit(1);
    });
    process.on('SIGINT', () => {
        console.error('Received SIGINT, writing finished output and exiting');
        core.setOutput('finished', finishedOutput);
        process.exit(1);
    });

    const actionStartedAt = Math.floor(Date.now() / 1000);

    try {
        const finished = core.getBooleanInput('finished', { required: true });
        const from_artifact = core.getBooleanInput('from_artifact', { required: true });
        const target = core.getInput('target', {required: true});
        const targetPolicy = getTargetPolicy(target);
        const githubToken = core.getInput('github_token') || core.getInput('github-token') || process.env.GITHUB_TOKEN || '';
        console.log(`finished: ${finished}, artifact: ${from_artifact}`);
        if (finished) {
            finishedOutput = true;
            return;
        }

        const GITHUB_WORKSPACE = process.env.GITHUB_WORKSPACE || process.cwd();
        const BUILD_DIR = `${GITHUB_WORKSPACE}/build`;

        const artifact = new DefaultArtifactClient();
        const artifactName = targetPolicy.cacheArtifact;
        const archivePath = `${GITHUB_WORKSPACE}/artifacts.tar.zst`;

        if (from_artifact) {
            await io.mkdirP(BUILD_DIR);
            const restored = await restoreFromArtifacts(artifact, artifactName, archivePath, BUILD_DIR, GITHUB_WORKSPACE);
            if (!restored) {
                return;
            }
        }

        const args = ['build.py', '--ci', '-j', '4', '--7z-path', '/usr/bin/7z', '--target', target];
        await exec.exec('python3', ['-m', 'pip', 'install', 'httplib2==0.22.0'], {
            cwd: GITHUB_WORKSPACE,
            ignoreReturnCode: true
        });

        // x86: 18,600s (5h 10m), arm64: 18,600s (5h 10m), x64: 18,900s (5h 15m).
        const maximumBuildSeconds = targetPolicy.maximumBuildSeconds;
        // x86: 2,100s (35m), arm64: 2,400s (40m), x64: 2,100s (35m).
        // This covers the timeout grace period, unmounting, compression, and artifact upload.
        const reserveSeconds = targetPolicy.reserveSeconds;
        // Query true job creation timestamp from GitHub API to account for queuing delay against 6-hour limit.
        const jobTimeInfo = await getJobTimeInfo(githubToken);
        // Date.now() returns milliseconds, so divide by 1000 to include setup and query time in Unix seconds.
        const nowSeconds = Math.floor(Date.now() / 1000);

        let remainingBuildSeconds;
        if (jobTimeInfo?.createdAt && jobTimeInfo.createdAt > 0 && jobTimeInfo.createdAt <= nowSeconds) {
            const totalElapsedSeconds = nowSeconds - jobTimeInfo.createdAt;
            if (jobTimeInfo.startedAt) {
                const queueSeconds = Math.max(0, jobTimeInfo.startedAt - jobTimeInfo.createdAt);
                console.log(`Job queue delay: ${queueSeconds}s (queued: ${jobTimeInfo.createdAtISO}, elapsed: ${totalElapsedSeconds}s)`);
            } else {
                console.log(`Job total elapsed: ${totalElapsedSeconds}s (queued: ${jobTimeInfo.createdAtISO})`);
            }
            // 21,600s is GitHub-hosted runners' six-hour job limit calculated from job creation.
            remainingBuildSeconds = 21600 - totalElapsedSeconds - reserveSeconds;
        } else {
            // Fallback when API job metadata is unavailable: deduct action setup time and apply 30m conservative buffer for unmeasured queue delay.
            const actionElapsedSeconds = Math.max(0, nowSeconds - actionStartedAt);
            const fallbackRedundancySeconds = 1800;
            console.log(`Using fallback budget: action elapsed ${actionElapsedSeconds}s, reserved ${fallbackRedundancySeconds}s buffer for queue delay`);
            remainingBuildSeconds = 21600 - actionElapsedSeconds - fallbackRedundancySeconds - reserveSeconds;
        }

        // Stop at whichever limit is reached first.
        const buildTimeoutSeconds = Math.min(maximumBuildSeconds, remainingBuildSeconds);
        console.log(`Build time budget: maximum=${maximumBuildSeconds}s, reserve=${reserveSeconds}s, remaining=${remainingBuildSeconds}s, timeout=${buildTimeoutSeconds}s`);

        if (buildTimeoutSeconds < 60) {
            if (from_artifact) {
                console.log(`Only ${buildTimeoutSeconds}s remain before the reserved job time. Retaining the restored cache artifact for the next runner...`);
                return;
            }

            throw new Error(`Only ${buildTimeoutSeconds}s remain before the reserved job time, and no cache artifact is available for the next runner`);
        }

        const timeoutArgs = ['-v', '-k', '5m', '-s', 'INT', buildTimeoutSeconds.toString(), 'python3', ...args];

        const retCode = await exec.exec('timeout', timeoutArgs, {
            cwd: GITHUB_WORKSPACE,
            ignoreReturnCode: true
        });
        if (retCode === 0) {
            const globber = await glob.create(`${BUILD_DIR}/ungoogled-chromium*`, { matchDirectories: false });
            let packageList = await globber.glob();
            const finalArtifactName = targetPolicy.finalArtifact;
            await uploadArtifactWithRetry(artifact, finalArtifactName, packageList, BUILD_DIR,
                'Upload artifact failed');
            finishedOutput = true;
        } else if (retCode === 124) {
            console.log('Build safely timed out (124). Preparing cache artifact for the next runner...');
            await sleep(5000);

            // Unmount ciopfs before archiving to avoid packing the FUSE mountpoint
            const vsFilesMount = `${BUILD_DIR}/src/third_party/depot_tools/win_toolchain/vs_files`;
            try {
                await ensureUnmounted(vsFilesMount);
            } catch (e) {
                console.error(`Failed to prepare safe archive state: ${e}`);
                throw new Error('vs_files is still mounted after retrying; aborting artifact archival');
            }

            // Show source directory size before compression
            const srcDir = `${BUILD_DIR}/src`;
            console.log('Source directory:');
            await exec.exec('du', ['-sh', srcDir], { ignoreReturnCode: true });
            // Create compressed archive using tar + zstd
            console.log(`Creating archive: ${archivePath}`);
            console.log('Compression started...');
            await exec.exec('tar', [
                '-I', 'zstd -10 -T0',
                '-cf', archivePath,
                '-C', BUILD_DIR,
                '--exclude=src/third_party/depot_tools/win_toolchain/vs_files',
                'src'
            ], { ignoreReturnCode: true });
            console.log('Compression completed');
            // Show compressed file size
            console.log('Compressed archive:');
            await exec.exec('du', ['-sh', archivePath], { ignoreReturnCode: true });

            await uploadArtifactWithRetry(artifact, artifactName, [archivePath], GITHUB_WORKSPACE,
                'Upload artifact failed');
        } else {
            throw new Error(`Build failed with critical error code: ${retCode}`);
        }
    } finally {
        core.setOutput('finished', finishedOutput);
    }
}

run().catch(err => core.setFailed(err.message));
