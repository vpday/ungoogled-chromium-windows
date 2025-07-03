const core = require('@actions/core');
const io = require('@actions/io');
const exec = require('@actions/exec');
const {DefaultArtifactClient} = require('@actions/artifact');
const glob = require('@actions/glob');
const path = require('path');

async function run() {
    // Use GitHub workspace or current working directory as base path
    const workingDir = await (async () => {
        const originalPath = process.env.GITHUB_WORKSPACE || process.cwd();
        const shortPath = "D:\\ungoogled-chromium-windows";

        try {
            await exec.exec('mklink', ['/d', shortPath, originalPath]);
            return shortPath;
        } catch (e) {
            console.error('Symlink fallback failed, trying git longpaths...');
            await exec.exec('git', ['config', '--global', 'core.longpaths', 'true']);
        }

        return originalPath;
    })();
    const buildDir = path.join(workingDir, 'build');

    console.log(`Working directory: ${workingDir}`);
    console.log(`Build directory: ${buildDir}`);

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

    const startTime = Date.now();
    const artifact = new DefaultArtifactClient();
    const artifactName = x86 ? 'build-artifact-x86' : (arm ? 'build-artifact-arm' : 'build-artifact');

    if (from_artifact) {
        const artifactInfo = await artifact.getArtifact(artifactName);
        await artifact.downloadArtifact(artifactInfo.artifact.id, {path: buildDir});
        await exec.exec('7z', ['x', path.join(buildDir, 'artifacts.zip'),
            `-o${buildDir}`, '-y']);
        await io.rmRF(path.join(buildDir, 'artifacts.zip'));
    }

    const args = ['build.py', '--ci']
    if (x86)
        args.push('--x86')
    if (arm)
        args.push('--arm')

    const env = {
        ...process.env,
        GH_ACTIONS_START_TIME: startTime.toString()
    };

    await exec.exec('python', ['-m', 'pip', 'install', 'httplib2'], {
        cwd: workingDir,
        ignoreReturnCode: true
    });
    const retCode = await exec.exec('python', args, {
        cwd: workingDir,
        ignoreReturnCode: true,
        env: env
    });
    if (retCode === 0) {
        core.setOutput('finished', true);
        const globber = await glob.create(path.join(buildDir, 'ungoogled-chromium*'),
            {matchDirectories: false});
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
                    buildDir, {retentionDays: 1, compressionLevel: 0});
                break;
            } catch (e) {
                console.error(`Upload artifact failed: ${e}`);
                // Wait 10 seconds between the attempts
                await new Promise(r => setTimeout(r, 10000));
            }
        }
    } else {
        await new Promise(r => setTimeout(r, 5000));
        await exec.exec('7z', ['a', '-tzip', path.join(workingDir, 'artifacts.zip'),
            path.join(buildDir, 'src'), '-mx=3', '-mtc=on'], {ignoreReturnCode: true});
        for (let i = 0; i < 5; ++i) {
            try {
                await artifact.deleteArtifact(artifactName);
            } catch (e) {
                // ignored
            }
            try {
                await artifact.uploadArtifact(artifactName, [path.join(workingDir, 'artifacts.zip')],
                    workingDir, {retentionDays: 1, compressionLevel: 0});
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
