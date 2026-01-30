const core = require('@actions/core');
const io = require('@actions/io');
const exec = require('@actions/exec');
const {DefaultArtifactClient} = require('@actions/artifact');
const glob = require('@actions/glob');
const fs = require('fs');

async function run() {
    process.on('SIGINT', function() {
    })
    const finished = core.getBooleanInput('finished', {required: true});
    const from_artifact = core.getBooleanInput('from_artifact', {required: true});
    const x86 = core.getBooleanInput('x86', {required: false})
    const arm = core.getBooleanInput('arm', {required: false})
    console.log(`finished: ${finished}, artifact: ${from_artifact}`);
    if (finished) {
        core.setOutput('finished', true);
        return;
    }

    const WORK_DIR = '/mnt/chromium-build';
    const BUILD_DIR = `${WORK_DIR}/build`;
    const GITHUB_WORKSPACE = process.env.GITHUB_WORKSPACE || process.cwd();
    console.log(`Working Directory: ${WORK_DIR}`);

    const artifact = new DefaultArtifactClient();
    const artifactName = x86 ? 'build-artifact-x86' : (arm ? 'build-artifact-arm' : 'build-artifact');

    if (from_artifact) {
        const artifactInfo = await artifact.getArtifact(artifactName);
        await artifact.downloadArtifact(artifactInfo.artifact.id, {path: `${GITHUB_WORKSPACE}/build`});
        await exec.exec('mkdir', ['-p', BUILD_DIR]);
        const archivePath = `${GITHUB_WORKSPACE}/build/artifacts.tar.zst`;
        await exec.exec('tar', ['-I', 'zstd -T0', '-xf', archivePath, '-C', BUILD_DIR]);
        await io.rmRF(`${GITHUB_WORKSPACE}/build`);

        // Clean up ciopfs directories if they were included in the artifact
        const vsFilesPath = `${BUILD_DIR}/src/third_party/depot_tools/win_toolchain/vs_files`;
        const vsCiopfsPath = `${vsFilesPath}.ciopfs`;
        if (fs.existsSync(vsFilesPath)) {
            console.log(`Removing ciopfs mountpoint directory: ${vsFilesPath}`);
            await io.rmRF(vsFilesPath);
        }
        if (fs.existsSync(vsCiopfsPath)) {
            console.log(`Removing ciopfs source directory: ${vsCiopfsPath}`);
            await io.rmRF(vsCiopfsPath);
        }
    }

    const args = ['build.py', '--ci', '-j', '2', '--7z-path', '/usr/bin/7z']
    if (x86)
        args.push('--x86')
    if (arm)
        args.push('--arm')
    await exec.exec('python3', ['-m', 'pip', 'install', 'httplib2==0.22.0'], {
        cwd: WORK_DIR,
        ignoreReturnCode: true
    });
    const retCode = await exec.exec('python3', args, {
        cwd: WORK_DIR,
        ignoreReturnCode: true
    });
    if (retCode === 0) {
        core.setOutput('finished', true);
        const globber = await glob.create(`${BUILD_DIR}/ungoogled-chromium*`, {matchDirectories: false});
        let packageList = await globber.glob();
        const finalArtifactName = x86 ? 'chromium-x86' : (arm ? 'chromium-arm' : 'chromium');
        for (let i = 0; i < 5; ++i) {
            try {
                await artifact.deleteArtifact(finalArtifactName);
            } catch (e) {
                // ignored
            }
            try {
                await artifact.uploadArtifact(finalArtifactName, packageList,
                    BUILD_DIR, {retentionDays: 4, compressionLevel: 0});
                break;
            } catch (e) {
                console.error(`Upload artifact failed: ${e}`);
                // Wait 10 seconds between the attempts
                await new Promise(r => setTimeout(r, 10000));
            }
        }
    } else {
        await new Promise(r => setTimeout(r, 5000));

        // Show source directory size before compression
        const srcDir = `${BUILD_DIR}/src`;
        console.log('Source directory:');
        await exec.exec('du', ['-sh', srcDir]);
        // Create compressed archive using tar + zstd
        const archivePath = `${GITHUB_WORKSPACE}/artifacts.tar.zst`;
        console.log(`Creating archive: ${archivePath}`);
        console.log('Compression started...');
        await exec.exec('tar', [
            '-I', 'zstd -10 -T0',
            '-cf', archivePath,
            '-C', BUILD_DIR,
            '--exclude=src/third_party/depot_tools/win_toolchain/vs_files',
            '--exclude=src/third_party/depot_tools/win_toolchain/vs_files.ciopfs',
            'src'
        ], {ignoreReturnCode: true});
        console.log('Compression completed');
        // Show compressed file size
        console.log('Compressed archive:');
        await exec.exec('du', ['-sh', archivePath]);

        for (let i = 0; i < 5; ++i) {
            try {
                await artifact.deleteArtifact(artifactName);
            } catch (e) {
                // ignored
            }
            try {
                await artifact.uploadArtifact(artifactName, [archivePath],
                    GITHUB_WORKSPACE, {retentionDays: 4, compressionLevel: 0});
                break;
            } catch (e) {
                console.error(`Upload artifact failed: ${e}`);
                // Wait 10 seconds between the attempts
                await new Promise(r => setTimeout(r, 10000));
            }
        }
        core.setOutput('finished', false);
    }
}

run().catch(err => core.setFailed(err.message));
