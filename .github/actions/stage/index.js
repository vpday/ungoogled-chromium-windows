import * as core from '@actions/core';
import * as io from '@actions/io';
import * as exec from '@actions/exec';
import { DefaultArtifactClient } from '@actions/artifact';
import * as glob from '@actions/glob';
import fs from 'fs';

let finishedOutput = false;

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

    try {
        const finished = core.getBooleanInput('finished', { required: true });
        const from_artifact = core.getBooleanInput('from_artifact', { required: true });
        const x86 = core.getBooleanInput('x86', { required: false })
        const arm = core.getBooleanInput('arm', { required: false })
        console.log(`finished: ${finished}, artifact: ${from_artifact}`);
        if (finished) {
            finishedOutput = true;
            return;
        }

        const GITHUB_WORKSPACE = process.env.GITHUB_WORKSPACE || process.cwd();
        const BUILD_DIR = `${GITHUB_WORKSPACE}/build`;

        const artifact = new DefaultArtifactClient();
        const artifactName = x86 ? 'build-artifact-x86' : (arm ? 'build-artifact-arm' : 'build-artifact');
        const archivePath = `${GITHUB_WORKSPACE}/artifacts.tar.zst`;

        if (from_artifact) {
            await io.mkdirP(BUILD_DIR);
            const restored = await restoreFromArtifacts(artifact, artifactName, archivePath, BUILD_DIR, GITHUB_WORKSPACE);
            if (!restored) {
                return;
            }
        }

        const args = ['build.py', '--ci', '-j', '4', '--7z-path', '/usr/bin/7z']
        if (x86)
            args.push('--x86')
        if (arm)
            args.push('--arm')
        await exec.exec('python3', ['-m', 'pip', 'install', 'httplib2==0.22.0'], {
            cwd: GITHUB_WORKSPACE,
            ignoreReturnCode: true
        });

        // Use timeout command to enforce architecture-specific build limits:
        // x86: 5h 10m (18600s), arm: 5h (18000s), x64: 5h 15m (18900s)
        const buildTimeoutSeconds = x86 ? 18600 : (arm ? 18000 : 18900);
        const timeoutArgs = ['-v', '-k', '5m', '-s', 'INT', buildTimeoutSeconds.toString(), 'python3', ...args];

        const retCode = await exec.exec('timeout', timeoutArgs, {
            cwd: GITHUB_WORKSPACE,
            ignoreReturnCode: true
        });
        if (retCode === 0) {
            const globber = await glob.create(`${BUILD_DIR}/ungoogled-chromium*`, { matchDirectories: false });
            let packageList = await globber.glob();
            const finalArtifactName = x86 ? 'chromium-x86' : (arm ? 'chromium-arm' : 'chromium');
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
